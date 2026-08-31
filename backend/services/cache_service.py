"""Semantic Cache — reuse answers for semantically identical questions, spending no LLM tokens.

Sales staff ask the same thing over and over in different wordings ("giá căn 2PN?",
"căn 2PN bao nhiêu tiền?"). A literal string cache misses all of those, so matching here
is done on the **question vector**: if cosine similarity against an already-answered
question is high enough, the stored answer is returned directly, skipping the entire
Retrieve → Generate → Verify chain.

The cache lives in its **own** Qdrant collection (`salesmate_qa_cache`), separate from the
document collection, so clearing the cache can never touch ingested document vectors.

The principle throughout this file: **if the cache breaks, fail silently**. It is a cost
optimisation, not a source of truth — letting it raise into the pipeline would turn a
trivial Qdrant hiccup into a total inability to answer, when the only real cost of
skipping it is a few extra tokens.
"""

import logging
import uuid
from dataclasses import dataclass, field

from qdrant_client import models

from backend.core.config import settings
from backend.core.enums import DocumentVisibility
from backend.core.gemini_client import embed_query
from backend.core.qdrant_client import get_qdrant_client

logger = logging.getLogger(__name__)

CACHE_COLLECTION = "salesmate_qa_cache"

CACHE_SIMILARITY_THRESHOLD = 0.95


@dataclass
class CachedAnswer:
    answer: str
    citations: list[dict]
    verifier_score: float
    images: list[dict] = field(default_factory=list)


def lookup_cache(
    query: str, project_id: str | None = None, clearance: DocumentVisibility = DocumentVisibility.INTERNAL
) -> CachedAnswer | None:
    """Find a cached answer for an equivalent question. `None` means a cache miss.

    `clearance` scopes the lookup to the asker's own RBAC tier: a PUBLIC-clearance asker
    (customer chat) must never receive an answer that was generated and cached for an
    INTERNAL-clearance asker (Sale/Admin), since that answer may have drawn on internal
    documents. See `store_cache` for the write-side half of this.
    """
    if not query.strip():
        return None

    try:
        client = get_qdrant_client()
        if not client.collection_exists(CACHE_COLLECTION):
            return None

        response = client.query_points(
            collection_name=CACHE_COLLECTION,
            query=embed_query(query),
            query_filter=_cache_filter(project_id, clearance),
            limit=1,
            with_payload=True,
        )
    except Exception:
        logger.warning(
            "Cache lookup failed; treating as a miss.",
            exc_info=True,
            extra={"event": "cache.lookup.failed", "project_id": project_id},
        )
        return None

    if not response.points:
        return None

    hit = response.points[0]
    similarity = (hit.score + 1.0) / 2.0
    if similarity < CACHE_SIMILARITY_THRESHOLD:
        return None

    payload = hit.payload or {}
    answer = payload.get("answer")
    if not answer:
        return None

    return CachedAnswer(
        answer=answer,
        citations=payload.get("citations") or [],
        verifier_score=payload.get("verifier_score") or 0.0,
        images=payload.get("images") or [],
    )


def store_cache(
    query: str,
    answer: str,
    citations: list[dict],
    verifier_score: float,
    project_id: str | None = None,
    images: list[dict] | None = None,
    clearance: DocumentVisibility = DocumentVisibility.INTERNAL,
) -> None:
    """Store a (question, answer) pair that has met the quality bar.

    Callers are responsible for **not** calling this for answers with `requires_hitl` or
    below the verifier threshold — see `agent_pipeline`. Rationale: price/commitment
    answers must go through Verify + RiskCheck every time so the Sale always sees the
    HITL card, and caching a low-scoring answer merely replicates a bad answer.

    `clearance` is written into the point id and payload so an INTERNAL-tier answer can
    never be overwritten by, or served back as, a PUBLIC-tier one for the same question —
    see `lookup_cache`.
    """
    if not query.strip() or not answer.strip():
        return

    try:
        _ensure_cache_collection()

        get_qdrant_client().upsert(
            collection_name=CACHE_COLLECTION,
            points=[
                models.PointStruct(
                    id=str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"salesmate:qa:{clearance.value}:{project_id or ''}:{query.strip()}",
                        )
                    ),
                    vector=embed_query(query),
                    payload={
                        "query": query,
                        "answer": answer,
                        "citations": citations,
                        "images": images or [],
                        "verifier_score": verifier_score,
                        "project_id": project_id,
                        "visibility": clearance.value,
                    },
                )
            ],
        )
    except Exception:
        logger.warning(
            "Cache write failed; the answer already served is unaffected.",
            exc_info=True,
            extra={"event": "cache.store.failed", "project_id": project_id},
        )
        return


def clear_cache() -> None:
    """Drop every cached answer.

    Cached answers have no reference back to which documents they drew on, so there is no
    way to invalidate just the entries a specific document change might affect — this is
    the only lever available. Called when an Admin changes a document's visibility (see
    routers/documents.py::set_document_visibility): otherwise a question asked and cached
    while a document was still internal keeps serving that stale "no data" answer forever
    after the document goes public, since the cache has no idea anything changed. Safe to
    call anytime — this is a cost optimisation, not a source of truth (see module
    docstring); the only cost of clearing it early is a few extra tokens on the next ask.
    """
    try:
        client = get_qdrant_client()
        if client.collection_exists(CACHE_COLLECTION):
            client.delete_collection(CACHE_COLLECTION)
    except Exception:
        logger.warning(
            "Cache clear failed; stale cached answers may persist until they expire on their own.",
            exc_info=True,
            extra={"event": "cache.clear.failed"},
        )


def _ensure_cache_collection() -> None:
    client = get_qdrant_client()
    if client.collection_exists(CACHE_COLLECTION):
        return

    client.create_collection(
        collection_name=CACHE_COLLECTION,
        vectors_config=models.VectorParams(
            size=settings.embedding_dimensions,
            distance=models.Distance.COSINE,
        ),
    )
    client.create_payload_index(
        collection_name=CACHE_COLLECTION,
        field_name="project_id",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )
    client.create_payload_index(
        collection_name=CACHE_COLLECTION,
        field_name="visibility",
        field_schema=models.PayloadSchemaType.KEYWORD,
    )


def _cache_filter(project_id: str | None, clearance: DocumentVisibility) -> models.Filter:
    """Scope a cache lookup to the same project AND the same asker clearance.

    Project: stops one project's cache from answering for another — prices and policies
    differ entirely. A session with no project may only reuse cache entries that also have
    no project, since an answer specific to one project does not generalise to a generic
    question.

    Clearance: a point cached before this field existed has no `visibility` payload key at
    all, so it matches neither tier here and is simply never hit again — a cache miss, not
    a leak, which is the safe direction to fail in.
    """
    conditions: list[models.Condition] = [
        models.FieldCondition(key="visibility", match=models.MatchValue(value=clearance.value))
    ]

    if project_id is None:
        conditions.append(models.IsNullCondition(is_null=models.PayloadField(key="project_id")))
    else:
        conditions.append(models.FieldCondition(key="project_id", match=models.MatchValue(value=project_id)))

    return models.Filter(must=conditions)
