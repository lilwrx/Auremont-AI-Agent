import logging
import time
import uuid
from typing import Any, TypeVar, cast

import google.genai as genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel

from backend.core import tracing
from backend.core.config import settings

logger = logging.getLogger(__name__)

_EMBED_MAX_ATTEMPTS = 4
_EMBED_RETRY_STATUS_CODES = {429}

_GENERATE_MAX_ATTEMPTS = 2
_GENERATE_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}
_GENERATE_MAX_RETRY_DELAY_SECONDS = 1.0

ModelT = TypeVar("ModelT", bound=BaseModel)

_client: genai.Client | None = None


def is_gemini_quota_error(exc: BaseException) -> bool:
    """Return whether ``exc`` (or one of its causes) is Gemini quota exhaustion.

    Service layers deliberately wrap SDK exceptions before they cross their boundary.
    Walking the exception chain here lets those layers retain a useful, provider-neutral
    error for Admins without copying SDK response parsing throughout the application.
    Only actual google-genai API errors qualify, so an unrelated service returning HTTP
    429 cannot accidentally be reported as an AI quota problem.
    """

    current: BaseException | None = exc
    visited: set[int] = set()
    while current is not None and id(current) not in visited:
        visited.add(id(current))
        if isinstance(current, genai_errors.APIError):
            if getattr(current, "code", None) == 429:
                return True

            body = getattr(current, "details", None)
            error = body.get("error") if isinstance(body, dict) else None
            if isinstance(error, dict) and error.get("status") == "RESOURCE_EXHAUSTED":
                return True

        current = current.__cause__ or current.__context__

    return False


def get_gemini_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _client


def generate_text(prompt: str, system_instruction: str | None = None) -> str:
    config = (
        types.GenerateContentConfig(
            system_instruction=system_instruction,
        )
        if system_instruction
        else None
    )

    return client_models_generate(prompt, config).text or ""


def generate_json(
    prompt: str,
    schema: type[ModelT],
    system_instruction: str | None = None,
    *,
    temperature: float | None = None,
) -> ModelT | None:
    """Generate a response constrained to `schema`, returning a parsed model instance.

    Uses Gemini's schema-constrained decoding rather than asking for JSON in the prompt
    and parsing whatever comes back. Critical AI decisions (verification scores, risk
    classification) must not depend on a regex finding a brace in prose.

    Returns None when the model returns nothing parseable; callers decide what a missing
    judgement means, and for verification it means fail closed.
    """
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        response_mime_type="application/json",
        response_schema=schema,
        temperature=temperature,
    )

    response = client_models_generate(prompt, config)
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, schema):
        return parsed

    raw = (response.text or "").strip()
    if not raw:
        return None
    return schema.model_validate_json(raw)


def client_models_generate(prompt: str, config):
    """The single entry point for every generation call, so the retry policy above cannot
    drift between the plain-text and schema-constrained paths."""
    for attempt in range(1, _GENERATE_MAX_ATTEMPTS + 1):
        try:
            response = get_gemini_client().models.generate_content(
                model=settings.GEMINI_MODEL,
                contents=prompt,
                config=config,
            )
            usage = getattr(response, "usage_metadata", None)
            if usage is not None:
                input_tokens = int(getattr(usage, "prompt_token_count", 0) or 0)
                output_tokens = int(getattr(usage, "candidates_token_count", 0) or 0)
                total_tokens = int(getattr(usage, "total_token_count", 0) or input_tokens + output_tokens)
                usage_id = uuid.uuid4().hex
                tracing.step(
                    "llm.usage",
                    usage_id=usage_id,
                    model=settings.GEMINI_MODEL,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    total_tokens=total_tokens,
                )
                if settings.observability_metrics_enabled:
                    try:
                        from backend.core.observability_sink import persist_llm_usage

                        persist_llm_usage(
                            usage_id=usage_id,
                            run_id=tracing.current_run_id(),
                            operation="gemini_generation",
                            model=settings.GEMINI_MODEL,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=total_tokens,
                        )
                    except Exception:  # pragma: no cover - metrics must never break generation
                        logger.warning(
                            "Could not record Gemini token usage.",
                            exc_info=True,
                            extra={"event": "observability.usage.record.failed"},
                        )
            return response
        except genai_errors.APIError as exc:
            if exc.code not in _GENERATE_RETRY_STATUS_CODES or attempt == _GENERATE_MAX_ATTEMPTS:
                raise

            delay = min(retry_delay_seconds(exc), _GENERATE_MAX_RETRY_DELAY_SECONDS)
            logger.warning(
                "Gemini generation hit a transient fault; retrying once.",
                extra={
                    "event": "gemini.generate.retry",
                    "model": settings.GEMINI_MODEL,
                    "status_code": exc.code,
                    "attempt": attempt,
                    "delay_seconds": delay,
                },
            )
            time.sleep(delay)

    raise RuntimeError("Gemini generation retry loop exited without a result.")


class GeminiEmbeddingError(RuntimeError):
    """Gemini did not return a valid embedding."""


def embed_documents(texts: list[str], *, title: str) -> list[list[float]]:
    """Embed document chunks for storage in Qdrant.

    Uses RETRIEVAL_DOCUMENT because these are vectors of source data,
    not of a search query.
    """
    return _embed(
        texts,
        task_type="RETRIEVAL_DOCUMENT",
        title=title,
    )


def embed_query(query: str) -> list[float]:
    """Embed a query for retrieval against Qdrant."""
    vectors = _embed(
        [query],
        task_type="RETRIEVAL_QUERY",
        title=None,
    )
    return vectors[0]


def _embed(
    texts: list[str],
    *,
    task_type: str,
    title: str | None,
) -> list[list[float]]:
    if not texts:
        return []

    config_kwargs: dict = {
        "task_type": task_type,
        "output_dimensionality": settings.embedding_dimensions,
    }

    if title:
        config_kwargs["title"] = title

    response = None
    for attempt in range(1, _EMBED_MAX_ATTEMPTS + 1):
        try:
            response = get_gemini_client().models.embed_content(
                model=settings.embedding_model,
                contents=cast(Any, texts),
                config=types.EmbedContentConfig(**config_kwargs),
            )
            break
        except genai_errors.APIError as exc:
            is_last_attempt = attempt == _EMBED_MAX_ATTEMPTS
            if exc.code not in _EMBED_RETRY_STATUS_CODES or is_last_attempt:
                logger.exception(
                    "Gemini embedding call failed.",
                    extra={
                        "event": "gemini.embed.failed",
                        "model": settings.embedding_model,
                        "input_count": len(texts),
                        "status_code": exc.code,
                        "attempt": attempt,
                    },
                )
                raise GeminiEmbeddingError("Gemini embedding request failed.") from exc

            delay = retry_delay_seconds(exc)
            logger.warning(
                "Gemini embedding rate-limited; retrying.",
                extra={
                    "event": "gemini.embed.rate_limited",
                    "model": settings.embedding_model,
                    "input_count": len(texts),
                    "attempt": attempt,
                    "delay_seconds": delay,
                },
            )
            time.sleep(delay)
        except Exception as exc:
            logger.exception(
                "Gemini embedding call failed.",
                extra={"event": "gemini.embed.failed", "model": settings.embedding_model, "input_count": len(texts)},
            )
            raise GeminiEmbeddingError("Gemini embedding request failed.") from exc

    if response is None:
        raise GeminiEmbeddingError("Gemini embedding retries finished without a response.")

    if not response.embeddings:
        raise GeminiEmbeddingError("Gemini returned no embeddings.")

    vectors: list[list[float]] = []
    for embedding in response.embeddings:
        if embedding.values is None:
            raise GeminiEmbeddingError("Gemini returned an empty embedding.")
        vectors.append(embedding.values)

    if len(vectors) != len(texts):
        raise GeminiEmbeddingError("Gemini returned a different number of embeddings than inputs.")

    if any(len(vector) != settings.embedding_dimensions for vector in vectors):
        raise GeminiEmbeddingError("Gemini returned an embedding with an unexpected dimension.")

    return vectors


_DEFAULT_RETRY_DELAY_SECONDS = 20.0


def retry_delay_seconds(exc: genai_errors.APIError) -> float:
    """The 429 response itself names how long to back off (google.rpc.RetryInfo,
    e.g. "21s") — use it instead of guessing, falling back to a fixed default only if the
    response is ever shaped differently than the one this was built against.

    `exc.details` is the raw response body, `{"error": {..., "details": [...]}}` — note
    the outer "details" is the whole error object (APIError's own attribute name), the
    inner one is the list of google.rpc.* structs actually being searched here.
    """
    body = getattr(exc, "details", None)
    error = body.get("error") if isinstance(body, dict) else None
    entries = error.get("details") if isinstance(error, dict) else None
    if isinstance(entries, list):
        for entry in entries:
            retry_delay = isinstance(entry, dict) and entry.get("retryDelay")
            if isinstance(retry_delay, str) and retry_delay.endswith("s"):
                try:
                    return float(retry_delay[:-1])
                except ValueError:
                    pass
    return _DEFAULT_RETRY_DELAY_SECONDS
