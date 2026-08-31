"""Cohere Rerank v3.5 — the cross-encoder half of retrieval.

A cross-encoder scores query and passage together, so it catches relevance the dense/
BM25 channels miss individually: a passage can rank high on cosine or token overlap and
still not actually answer the question. Reranking narrows the over-fetched candidate set
down to the handful genuinely worth putting in the prompt.

Hosted rather than self-hosted (e.g. BGE-reranker-v2-m3): the backend runs on Render's
free tier, and loading a few-hundred-MB cross-encoder at cold start risks OOM there. The
trade-off is one network call per question instead of a one-time model load — acceptable
because reranking only runs on the already-narrow over-fetched set, not the whole corpus.
"""

import logging

import cohere

from backend.core.config import settings

logger = logging.getLogger(__name__)

_client: cohere.ClientV2 | None = None


class CohereRerankError(RuntimeError):
    """Cohere did not return a usable reranking."""


def get_cohere_client() -> cohere.ClientV2:
    global _client
    if _client is None:
        _client = cohere.ClientV2(
            api_key=settings.cohere_api_key,
            timeout=settings.cohere_rerank_timeout_seconds,
            max_retries=0,
        )
    return _client


def rerank(query: str, documents: list[str], *, top_n: int | None = None) -> list[tuple[int, float]]:
    """Rerank `documents` against `query`, returning (original_index, relevance_score).

    Ordered best-first. `top_n` trims server-side rather than in Python so a large
    over-fetched candidate set never pays for scores it will not use.
    """
    if not documents:
        return []

    try:
        response = get_cohere_client().rerank(
            model=settings.cohere_rerank_model,
            query=query,
            documents=documents,
            top_n=top_n or len(documents),
        )
    except Exception as exc:
        logger.exception(
            "Cohere rerank call failed.",
            extra={"event": "cohere.rerank.failed", "model": settings.cohere_rerank_model, "doc_count": len(documents)},
        )
        raise CohereRerankError("Cohere rerank request failed.") from exc

    results = getattr(response, "results", None)
    if not results:
        raise CohereRerankError("Cohere returned no rerank results.")

    return [(result.index, result.relevance_score) for result in results]
