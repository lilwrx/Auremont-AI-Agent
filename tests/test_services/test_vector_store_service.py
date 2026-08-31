from types import SimpleNamespace

import pytest
from qdrant_client import models

from backend.core.config import settings
from backend.services import vector_store_service
from backend.services.chunking_service import DocumentChunk


def _sparse(indices=(1, 2), values=(0.5, 0.5)) -> models.SparseVector:
    return models.SparseVector(indices=list(indices), values=list(values))


class FakeQdrantClient:
    def __init__(
        self,
        *,
        collection_exists: bool = False,
        collection_dimension: int = 3,
        legacy_unnamed: bool = False,
        has_sparse: bool = True,
    ):
        self.exists = collection_exists
        self.collection_dimension = collection_dimension
        self.legacy_unnamed = legacy_unnamed
        self.has_sparse = has_sparse

        self.create_calls = []
        self.upsert_calls = []
        self.delete_calls = []
        self.set_payload_calls = []
        self.payload_index_calls = []

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    def create_collection(self, **kwargs):
        self.create_calls.append(kwargs)
        self.exists = True

    def create_payload_index(self, **kwargs):
        self.payload_index_calls.append(kwargs)

    def get_collection(self, collection_name: str):
        if self.legacy_unnamed:
            vectors = SimpleNamespace(size=self.collection_dimension)
            sparse = None
        else:
            vectors = {"dense": SimpleNamespace(size=self.collection_dimension)}
            sparse = {"sparse": SimpleNamespace()} if self.has_sparse else None

        return SimpleNamespace(
            config=SimpleNamespace(
                params=SimpleNamespace(
                    vectors=vectors,
                    sparse_vectors=sparse,
                )
            )
        )

    def upsert(self, **kwargs):
        self.upsert_calls.append(kwargs)

    def delete(self, **kwargs):
        self.delete_calls.append(kwargs)

    def set_payload(self, **kwargs):
        self.set_payload_calls.append(kwargs)


@pytest.fixture
def qdrant(monkeypatch):
    fake_client = FakeQdrantClient()

    monkeypatch.setattr(
        vector_store_service,
        "get_qdrant_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(settings, "qdrant_collection", "test_documents")
    monkeypatch.setattr(settings, "embedding_dimensions", 3)

    return fake_client


def test_ensure_collection_creates_named_dense_and_sparse_vectors(qdrant):
    """Hybrid retrieval needs both vectors on the same point, so both must be declared."""
    vector_store_service.ensure_collection()

    assert len(qdrant.create_calls) == 1

    call = qdrant.create_calls[0]
    dense_config = call["vectors_config"]["dense"]

    assert call["collection_name"] == "test_documents"
    assert dense_config.size == 3
    assert dense_config.distance == models.Distance.COSINE
    assert isinstance(call["sparse_vectors_config"]["sparse"], models.SparseVectorParams)


def test_ensure_collection_rejects_wrong_dimension(monkeypatch):
    fake_client = FakeQdrantClient(
        collection_exists=True,
        collection_dimension=768,
    )

    monkeypatch.setattr(
        vector_store_service,
        "get_qdrant_client",
        lambda: fake_client,
    )
    monkeypatch.setattr(settings, "embedding_dimensions", 3)

    with pytest.raises(vector_store_service.VectorStoreError):
        vector_store_service.ensure_collection()


def test_ensure_collection_rejects_legacy_unnamed_schema(monkeypatch):
    """A collection from before hybrid retrieval cannot be upserted into — it must be
    rebuilt, and saying so beats writing points that only half work."""
    fake_client = FakeQdrantClient(collection_exists=True, legacy_unnamed=True)

    monkeypatch.setattr(vector_store_service, "get_qdrant_client", lambda: fake_client)
    monkeypatch.setattr(settings, "embedding_dimensions", 3)

    with pytest.raises(vector_store_service.VectorStoreError, match="predates hybrid"):
        vector_store_service.ensure_collection()


def test_ensure_collection_rejects_missing_sparse_config(monkeypatch):
    fake_client = FakeQdrantClient(collection_exists=True, has_sparse=False)

    monkeypatch.setattr(vector_store_service, "get_qdrant_client", lambda: fake_client)
    monkeypatch.setattr(settings, "embedding_dimensions", 3)

    with pytest.raises(vector_store_service.VectorStoreError, match="sparse"):
        vector_store_service.ensure_collection()


def test_index_document_chunks_upserts_expected_payload(qdrant):
    chunks = [
        DocumentChunk(index=0, text="Gia can 2PN tu 3.5 ty.", page=1),
        DocumentChunk(index=1, text="Chinh sach thanh toan.", page=2),
    ]
    vectors = [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]

    indexed_count = vector_store_service.index_document_chunks(
        document_id=12,
        title="bang-gia.pdf",
        project_id="project-a",
        visibility="internal",
        chunks=chunks,
        vectors=vectors,
        sparse_vectors=[_sparse(), _sparse(indices=(3, 4))],
    )

    assert indexed_count == 2
    assert len(qdrant.upsert_calls) == 1

    upsert_call = qdrant.upsert_calls[0]
    points = upsert_call["points"]

    assert upsert_call["collection_name"] == "test_documents"
    assert upsert_call["wait"] is True
    assert len(points) == 2

    first_point = points[0]
    assert first_point.vector == {"dense": [0.1, 0.2, 0.3], "sparse": _sparse()}
    assert first_point.payload == {
        "document_id": 12,
        "project_id": "project-a",
        "visibility": "internal",
        "title": "bang-gia.pdf",
        "page": 1,
        "chunk_index": 0,
        "content": "Gia can 2PN tu 3.5 ty.",
        "content_type": "prose",
        "y_position": None,
        "category": "other",
        "primary_category": "other",
        "document_categories": ["other"],
        "section_index": None,
        "review_status": "pending",
        "legal_status": "unknown",
        "is_current": True,
    }


def test_index_document_chunks_preserves_section_category_and_document_labels(qdrant):
    chunks = [
        DocumentChunk(
            index=0,
            text="Gia can A-01 la 3.5 ty.",
            page=2,
            category="price_list",
            section_index=4,
        )
    ]

    vector_store_service.index_document_chunks(
        document_id=21,
        title="tai-lieu-hon-hop.pdf",
        project_id="project-a",
        visibility="internal",
        chunks=chunks,
        vectors=[[0.1, 0.2, 0.3]],
        sparse_vectors=[_sparse()],
        category="sales_policy",
        categories=["sales_policy", "price_list"],
    )

    payload = qdrant.upsert_calls[0]["points"][0].payload
    assert payload["category"] == "price_list"
    assert payload["primary_category"] == "sales_policy"
    assert payload["document_categories"] == ["sales_policy", "price_list"]
    assert payload["section_index"] == 4


def test_index_document_chunks_carries_table_content_type(qdrant):
    """A chunk built from a detected PDF table must be identifiable in Qdrant, so
    Admin tooling can later report how many table chunks a document produced."""
    chunks = [
        DocumentChunk(index=0, text="|Loai|Gia|\n|2PN|3.5 ty|", page=1, content_type="table"),
    ]

    vector_store_service.index_document_chunks(
        document_id=12,
        title="bang-gia.pdf",
        project_id="project-a",
        visibility="internal",
        chunks=chunks,
        vectors=[[0.1, 0.2, 0.3]],
        sparse_vectors=[_sparse()],
    )

    point = qdrant.upsert_calls[0]["points"][0]
    assert point.payload["content_type"] == "table"


def test_index_document_chunks_uses_stable_point_ids(qdrant):
    chunks = [
        DocumentChunk(index=0, text="Noi dung chunk.", page=1),
    ]
    vectors = [
        [0.1, 0.2, 0.3],
    ]

    arguments = {
        "document_id": 99,
        "title": "tai-lieu.pdf",
        "project_id": None,
        "visibility": "internal",
        "chunks": chunks,
        "vectors": vectors,
        "sparse_vectors": [_sparse()],
    }

    vector_store_service.index_document_chunks(**arguments)
    vector_store_service.index_document_chunks(**arguments)

    first_id = qdrant.upsert_calls[0]["points"][0].id
    second_id = qdrant.upsert_calls[1]["points"][0].id

    assert first_id == second_id


def test_index_document_chunks_rejects_different_counts(qdrant):
    chunks = [
        DocumentChunk(index=0, text="Chunk mot.", page=1),
    ]
    vectors = [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]

    with pytest.raises(vector_store_service.VectorStoreError):
        vector_store_service.index_document_chunks(
            document_id=1,
            title="test.pdf",
            project_id=None,
            visibility="internal",
            chunks=chunks,
            vectors=vectors,
            sparse_vectors=[_sparse()],
        )

    assert qdrant.upsert_calls == []


def test_index_document_chunks_rejects_sparse_count_mismatch(qdrant):
    """A chunk with no sparse vector would be invisible to the keyword channel."""
    with pytest.raises(vector_store_service.VectorStoreError):
        vector_store_service.index_document_chunks(
            document_id=1,
            title="test.pdf",
            project_id=None,
            visibility="internal",
            chunks=[DocumentChunk(index=0, text="Chunk mot.", page=1)],
            vectors=[[0.1, 0.2, 0.3]],
            sparse_vectors=[],
        )

    assert qdrant.upsert_calls == []


def test_index_document_chunks_rejects_wrong_vector_dimension(qdrant):
    chunks = [
        DocumentChunk(index=0, text="Chunk mot.", page=1),
    ]
    vectors = [
        [0.1, 0.2],
    ]

    with pytest.raises(vector_store_service.VectorStoreError):
        vector_store_service.index_document_chunks(
            document_id=1,
            title="test.pdf",
            project_id=None,
            visibility="internal",
            chunks=chunks,
            vectors=vectors,
            sparse_vectors=[_sparse()],
        )

    assert qdrant.upsert_calls == []


def test_delete_document_vectors_filters_by_document_id(qdrant):
    qdrant.exists = True

    vector_store_service.delete_document_vectors(document_id=42)

    assert len(qdrant.delete_calls) == 1

    call = qdrant.delete_calls[0]
    assert call["collection_name"] == "test_documents"
    assert call["wait"] is True


def test_delete_document_vectors_ignores_a_missing_collection(qdrant):
    """Re-indexing starts by deleting old vectors; right after the collection was dropped
    there are none, and Qdrant's 404 must not abort the re-index before it writes."""
    qdrant.exists = False

    vector_store_service.delete_document_vectors(document_id=42)

    assert qdrant.delete_calls == []


def test_update_document_vector_metadata_updates_only_one_document(qdrant):
    qdrant.exists = True

    vector_store_service.update_document_vector_metadata(
        42,
        review_status="approved",
        legal_status="effective",
        category="legal_document",
        visibility="internal",
        is_current=False,
    )

    assert len(qdrant.set_payload_calls) == 1
    call = qdrant.set_payload_calls[0]
    assert call["collection_name"] == "test_documents"
    assert call["payload"] == {
        "review_status": "approved",
        "legal_status": "effective",
        "primary_category": "legal_document",
        "visibility": "internal",
        "is_current": False,
    }
    assert call["wait"] is True
