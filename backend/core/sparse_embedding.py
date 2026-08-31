"""BM25 sparse embeddings — the keyword half of hybrid retrieval.

Dense Gemini vectors capture meaning but blur exact tokens: "2PN" and "3PN" land almost
on top of each other, and a unit code like "OP3-CT1-0504" carries no meaning to embed at
all. BM25 scores literal token overlap instead, so those survive. `rag_service` runs both
channels and lets Qdrant fuse them with RRF.

Vectors are computed locally by FastEmbed — no API call, no per-token cost — which is why
running this on every ingested chunk and every question is affordable.

Vietnamese is folded to ASCII (`strip_diacritics`) before tokenising. BM25 matches tokens
exactly, and a Sale typing in front of a customer drops accents constantly, so "căn hộ"
and "can ho" have to reduce to the same token or the keyword channel misses precisely the
questions it exists to catch. The fold MUST be applied identically at ingest and at query
time; asymmetry here silently breaks every match. The dense channel keeps the original
accented text — Gemini handles Vietnamese natively.
"""

import logging
from functools import lru_cache

from fastembed import SparseTextEmbedding
from qdrant_client import models

from backend.core.config import get_settings
from backend.utils.text import strip_diacritics

logger = logging.getLogger(__name__)


class SparseEmbeddingError(RuntimeError):
    """The BM25 model could not be loaded, or produced no embedding."""


@lru_cache
def get_sparse_model() -> SparseTextEmbedding:
    """The shared BM25 model, loaded on first use.

    Loading is lazy so a cold cache costs the first request rather than blocking startup:
    a backend that cannot reach the model repository still boots and still answers, since
    `rag_service` degrades to dense-only when this raises.
    """
    settings = get_settings()
    try:
        return SparseTextEmbedding(model_name=settings.sparse_model_name)
    except Exception as exc:
        logger.exception(
            "Loading the BM25 sparse model failed.",
            extra={"event": "sparse.model.load_failed", "model": settings.sparse_model_name},
        )
        raise SparseEmbeddingError(f"Could not load sparse model '{settings.sparse_model_name}'.") from exc


def embed_documents_sparse(texts: list[str]) -> list[models.SparseVector]:
    """BM25 vectors for document chunks, in the order given."""
    if not texts:
        return []

    try:
        embeddings = list(get_sparse_model().embed([strip_diacritics(text) for text in texts]))
    except SparseEmbeddingError:
        raise
    except Exception as exc:
        raise SparseEmbeddingError("BM25 document embedding failed.") from exc

    if len(embeddings) != len(texts):
        raise SparseEmbeddingError("BM25 returned a different number of embeddings than inputs.")

    return [_to_sparse_vector(embedding) for embedding in embeddings]


def embed_query_sparse(query: str) -> models.SparseVector:
    """BM25 vector for one question.

    `query_embed` rather than `embed`: BM25 weights a query by IDF alone, with none of the
    term-frequency saturation applied to documents. Embedding a query as if it were a
    document would let a word repeated in the question inflate its own weight.
    """
    try:
        embeddings = list(get_sparse_model().query_embed(strip_diacritics(query)))
    except SparseEmbeddingError:
        raise
    except Exception as exc:
        raise SparseEmbeddingError("BM25 query embedding failed.") from exc

    if not embeddings:
        raise SparseEmbeddingError("BM25 returned no embedding for the query.")

    return _to_sparse_vector(embeddings[0])


def _to_sparse_vector(embedding) -> models.SparseVector:
    """FastEmbed returns numpy arrays; Qdrant's client wants plain Python lists."""
    return models.SparseVector(
        indices=embedding.indices.tolist(),
        values=embedding.values.tolist(),
    )
