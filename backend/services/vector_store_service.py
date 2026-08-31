import logging
import uuid
from typing import Any

from qdrant_client import models

from backend.core.config import settings
from backend.core.qdrant_client import get_qdrant_client
from backend.services.chunking_service import DocumentChunk
from backend.services.document_category_service import document_categories

logger = logging.getLogger(__name__)

DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"


class VectorStoreError(RuntimeError):
    """Failure while initialising the collection or writing vectors to Qdrant."""


_KEYWORD_INDEX_FIELDS = ("project_id", "visibility", "review_status", "category", "document_categories")


def _ensure_payload_indexes(client, collection_name: str) -> None:
    """Create indexes for every payload field `rag_service` filters on.

    Qdrant Cloud clusters run with strict mode on by default: a filter on a field
    with no index is rejected outright (400 Bad Request) rather than falling back
    to an unindexed scan the way self-hosted Qdrant does. `create_payload_index`
    is a no-op when the index already exists, so this is safe to call every time
    `ensure_collection` runs, not just on first creation.
    """
    for field in _KEYWORD_INDEX_FIELDS:
        client.create_payload_index(
            collection_name=collection_name,
            field_name=field,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="is_current",
        field_schema=models.PayloadSchemaType.BOOL,
    )
    client.create_payload_index(
        collection_name=collection_name,
        field_name="document_id",
        field_schema=models.PayloadSchemaType.INTEGER,
    )


def ensure_collection() -> None:
    """Create the dense+sparse collection if absent; reject a mismatched schema.

    Qdrant cannot add a named vector to points already written with a single unnamed one,
    so a collection built before hybrid retrieval has to be dropped and re-indexed rather
    than migrated in place. The checks below therefore fail loudly on the old shape: the
    alternative is an upsert that half-succeeds and leaves the keyword channel silently
    missing for those documents.
    """
    client = get_qdrant_client()
    collection_name = settings.qdrant_collection

    if not client.collection_exists(collection_name):
        client.create_collection(
            collection_name=collection_name,
            vectors_config={
                DENSE_VECTOR: models.VectorParams(
                    size=settings.embedding_dimensions,
                    distance=models.Distance.COSINE,
                ),
            },
            sparse_vectors_config={SPARSE_VECTOR: models.SparseVectorParams()},
        )
        _ensure_payload_indexes(client, collection_name)
        return

    collection = client.get_collection(collection_name)
    vectors = collection.config.params.vectors
    sparse_vectors = collection.config.params.sparse_vectors

    dense_params = vectors.get(DENSE_VECTOR) if isinstance(vectors, dict) else None
    if dense_params is None:
        raise VectorStoreError(
            f"Collection '{collection_name}' has no '{DENSE_VECTOR}' named vector. It predates hybrid "
            "retrieval — delete the collection and re-index every document."
        )

    if dense_params.size != settings.embedding_dimensions:
        raise VectorStoreError(
            f"Collection dimension is {dense_params.size}, but application expects {settings.embedding_dimensions}."
        )

    if not sparse_vectors or SPARSE_VECTOR not in sparse_vectors:
        raise VectorStoreError(
            f"Collection '{collection_name}' has no '{SPARSE_VECTOR}' sparse vector configured. "
            "Delete the collection and re-index every document."
        )

    _ensure_payload_indexes(client, collection_name)


def index_document_chunks(
    *,
    document_id: int,
    title: str,
    project_id: str | None,
    visibility: str,
    chunks: list[DocumentChunk],
    vectors: list[list[float]],
    sparse_vectors: list[models.SparseVector],
    review_status: str = "pending",
    legal_status: str = "unknown",
    category: str = "other",
    categories: list[str] | None = None,
    is_current: bool = True,
) -> int:
    """Write chunks with both their dense and sparse vectors into Qdrant.

    Both vectors are required. A point carrying only one of them is invisible to that
    half of hybrid retrieval, and the gap shows up as a document that simply never
    surfaces for keyword questions — far harder to notice than an outright failure here.
    """
    if len(chunks) != len(vectors) or len(chunks) != len(sparse_vectors):
        raise VectorStoreError("Number of chunks must match number of dense and sparse embeddings.")

    if not chunks:
        return 0

    if any(len(vector) != settings.embedding_dimensions for vector in vectors):
        raise VectorStoreError("An embedding has an unexpected dimension.")

    ensure_collection()

    points = [
        models.PointStruct(
            id=str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"salesmate:document:{document_id}:chunk:{chunk.index}",
                )
            ),
            vector={DENSE_VECTOR: vector, SPARSE_VECTOR: sparse_vector},
            payload={
                "document_id": document_id,
                "project_id": project_id,
                "visibility": visibility,
                "title": title,
                "page": chunk.page,
                "y_position": chunk.y_position,
                "chunk_index": chunk.index,
                "content": chunk.text,
                "content_type": chunk.content_type,
                "category": chunk.category or category,
                "primary_category": category,
                "document_categories": categories or [category],
                "section_index": chunk.section_index,
                "review_status": review_status,
                "legal_status": legal_status,
                "is_current": is_current,
            },
        )
        for chunk, vector, sparse_vector in zip(chunks, vectors, sparse_vectors, strict=True)
    ]

    try:
        get_qdrant_client().upsert(
            collection_name=settings.qdrant_collection,
            points=points,
            wait=True,
        )
    except Exception as exc:
        logger.exception(
            "Writing vectors to Qdrant failed.",
            extra={"event": "vector_store.upsert.failed", "point_count": len(points)},
        )
        raise VectorStoreError("Could not upsert vectors into Qdrant.") from exc

    return len(points)


def delete_document_vectors(document_id: int) -> None:
    """Delete every vector belonging to a document; used when deleting or re-indexing it.

    A missing collection means there is nothing to delete, which is the normal state when
    re-indexing after the collection was dropped — the same reasoning already applied in
    `update_document_vector_metadata`.
    """
    client = get_qdrant_client()
    if not client.collection_exists(settings.qdrant_collection):
        return

    try:
        client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
    except Exception as exc:
        logger.exception(
            "Deleting vectors for document %s failed.",
            document_id,
            extra={"event": "vector_store.delete.failed", "document_id": document_id},
        )
        raise VectorStoreError(f"Could not delete vectors for document {document_id}.") from exc


def update_document_vector_metadata(
    document_id: int,
    *,
    review_status: str,
    legal_status: str,
    category: str,
    categories: list[str] | None = None,
    visibility: str,
    is_current: bool,
) -> None:
    """Synchronise approval metadata for every existing chunk of one document.

    This does not re-embed content. It only changes Qdrant payload fields, which
    makes an Admin approval visible to retrieval immediately.
    """
    try:
        client = get_qdrant_client()
        if not client.collection_exists(settings.qdrant_collection):
            return

        client.set_payload(
            collection_name=settings.qdrant_collection,
            payload={
                "review_status": review_status,
                "legal_status": legal_status,
                "is_current": is_current,
                "primary_category": category,
                **({"document_categories": categories} if categories is not None else {}),
                "visibility": visibility,
            },
            points=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )
    except Exception as exc:
        raise VectorStoreError(f"Could not update vector metadata for document {document_id}.") from exc


def _enum_value(value: Any) -> str:
    return str(value.value if hasattr(value, "value") else value)


def sync_document_vector_metadata(document: Any, *, is_current: bool | None = None) -> None:
    """Synchronise vector metadata straight off an ORM `Document`, `categories` included.

    `update_document_vector_metadata` takes `categories` as an optional kwarg because a
    handful of callers restore from an old snapshot dict rather than a live document (see
    `document_vector_metadata_snapshot`/`restore_document_vector_metadata` below), and those
    snapshots predate the field. Every caller that *does* have the live ORM row should go
    through here instead of hand-listing five fields and forgetting `categories` — that
    omission was live for months: `document_categories` is a keyword-indexed Qdrant field
    (`_KEYWORD_INDEX_FIELDS` above) that `metadata_audit_service` cross-checks against
    MySQL, and a caller that skips it leaves retrieval filtering on stale category labels
    after a reclassification that changed `document.categories` but not `document.category`.
    """
    update_document_vector_metadata(
        document.id,
        review_status=_enum_value(document.review_status),
        legal_status=_enum_value(document.legal_status),
        category=_enum_value(document.category),
        categories=document_categories(document),
        visibility=_enum_value(document.visibility),
        is_current=bool(document.is_current if is_current is None else is_current),
    )


def document_vector_metadata_snapshot(document: Any) -> dict[str, object]:
    """Capture the fields `sync_document_vector_metadata` writes, for compensation."""
    return {
        "review_status": _enum_value(document.review_status),
        "legal_status": _enum_value(document.legal_status),
        "category": _enum_value(document.category),
        "categories": document_categories(document),
        "visibility": _enum_value(document.visibility),
        "is_current": bool(document.is_current),
    }


def restore_document_vector_metadata(
    document_id: int,
    metadata: dict[str, object],
) -> None:
    """Re-apply a metadata snapshot captured by `document_vector_metadata_snapshot`.

    Raises `VectorStoreError` on failure, same as `update_document_vector_metadata` — the
    caller decides whether that failure is fatal (a batch restore that must know whether to
    continue) or best-effort (log and swallow, see `log_and_swallow_restore_failure`).
    """
    raw_categories = metadata.get("categories")
    categories = [str(value) for value in raw_categories] if isinstance(raw_categories, list) else None
    update_document_vector_metadata(
        document_id,
        review_status=str(metadata["review_status"]),
        legal_status=str(metadata["legal_status"]),
        category=str(metadata["category"]),
        categories=categories,
        visibility=str(metadata["visibility"]),
        is_current=bool(metadata["is_current"]),
    )


def log_and_swallow_restore_failure(exc: VectorStoreError, *, document_id: int, event: str) -> None:
    """Shared logging for a best-effort `restore_document_vector_metadata` call.

    Called from inside the caller's own `except VectorStoreError as exc:` block, so
    `logger.exception` still picks up the live traceback via `sys.exc_info()` — `exc` is
    taken as a parameter only to make that call site self-documenting, not because the
    logger needs it passed explicitly.

    Used where the compensation attempt runs inside a handler for a failure the caller is
    about to re-raise: a second exception from the compensation itself would shadow the
    original one the client needs to see, so it is logged and swallowed instead.
    """
    del exc  # captured only via the active exception context; see docstring
    logger.exception(
        "Could not restore vector metadata after a cross-store operation failed.",
        extra={"event": event, "document_id": document_id},
    )
