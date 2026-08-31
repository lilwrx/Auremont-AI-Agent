"""Re-indexing a stored document — the route that migrates old vectors to a new shape.

Enabling hybrid retrieval changed what a Qdrant point looks like: it now carries a BM25
vector beside the dense one. Documents ingested before that have to be rewritten, and
this endpoint is how an Admin does it, one document at a time, from the original file
still held in MinIO.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.user import User
from backend.repositories.document import create_document
from backend.routers import documents as documents_router
from backend.schemas.document import DocumentCreate
from backend.services.ingestion_service import (
    AI_SERVICE_QUOTA_PUBLIC_MESSAGE,
    DocumentAIQuotaExceededError,
    DocumentIngestionError,
)


@pytest.fixture
def admin(db_session):
    user = User(username="admin1", email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sale(db_session):
    user = User(username="sale1", email="sale@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(db_session, admin):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def document(db_session, admin):
    return create_document(
        db_session,
        DocumentCreate(title="bang-gia.pdf", file_path="documents/1/abc-bang-gia.pdf"),
        uploaded_by=admin.id,
    )


def test_admin_can_reindex_a_stored_document(client, monkeypatch, document):
    calls = []
    monkeypatch.setattr(
        documents_router,
        "reindex_document",
        lambda db, *, document_id: calls.append(document_id) or document,
    )

    response = client.post(f"/api/v1/documents/{document.id}/reindex")

    assert response.status_code == 200, response.text
    assert calls == [document.id]
    assert response.json()["document_id"] == document.id


def test_a_failed_reindex_reports_an_error(client, monkeypatch, document):
    """Re-indexing deletes the old vectors first, so a silent failure would leave the
    document unreachable — the Admin has to be told it needs running again."""

    def _boom(db, *, document_id):
        raise DocumentIngestionError("MinIO unavailable")

    monkeypatch.setattr(documents_router, "reindex_document", _boom)

    response = client.post(f"/api/v1/documents/{document.id}/reindex")

    assert response.status_code == 500


def test_a_sale_cannot_reindex(db_session, sale, document):
    """Re-indexing rewrites the knowledge base; it stays an Admin-only operation."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: sale

    try:
        response = TestClient(app).post(f"/api/v1/documents/{document.id}/reindex")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


def test_admin_can_reclassify_a_document(client, monkeypatch, document):
    """The review endpoint refuses category edits, so this is the only in-app way to fix a
    document the classifier put in the wrong category."""
    calls = []
    monkeypatch.setattr(
        documents_router,
        "reclassify_document",
        lambda db, *, document_id, category, reviewed_by, metadata_updates=None: (
            calls.append((document_id, category)) or document
        ),
    )
    monkeypatch.setattr(documents_router, "clear_cache", lambda: None)

    response = client.post(f"/api/v1/documents/{document.id}/reclassify", json={"category": "price_list"})

    assert response.status_code == 200, response.text
    assert calls == [(document.id, "price_list")]


def test_reclassifying_clears_the_answer_cache(client, monkeypatch, document):
    """Its chunks and category both changed, so answers cached from it now cite a shape of
    the document that no longer exists."""
    cleared = []
    monkeypatch.setattr(
        documents_router,
        "reclassify_document",
        lambda db, *, document_id, category, reviewed_by, metadata_updates=None: document,
    )
    monkeypatch.setattr(documents_router, "clear_cache", lambda: cleared.append(True))

    client.post(f"/api/v1/documents/{document.id}/reclassify", json={"category": "price_list"})

    assert cleared == [True, True]


def test_an_unknown_category_is_rejected_before_any_work_starts(client, monkeypatch, document):
    called = []
    monkeypatch.setattr(
        documents_router,
        "reclassify_document",
        lambda db, **kwargs: called.append(kwargs) or document,
    )

    response = client.post(f"/api/v1/documents/{document.id}/reclassify", json={"category": "khong-ton-tai"})

    assert response.status_code == 422
    assert called == []


def test_a_failed_reclassify_reports_a_conflict(client, monkeypatch, document):
    """The document stays quarantined on failure, so the Admin can safely retry."""

    def _boom(db, **kwargs):
        raise DocumentIngestionError("Document 1 has no stored original file to re-index.")

    monkeypatch.setattr(documents_router, "reclassify_document", _boom)

    response = client.post(f"/api/v1/documents/{document.id}/reclassify", json={"category": "price_list"})

    assert response.status_code == 409
    assert "no stored original" in response.json()["detail"]


def test_ai_quota_during_reclassification_is_safe_and_actionable(client, monkeypatch, document):
    def _quota_exhausted(db, **kwargs):
        try:
            raise RuntimeError("provider payload with secret-key-value")
        except RuntimeError as exc:
            raise DocumentAIQuotaExceededError() from exc

    monkeypatch.setattr(documents_router, "reclassify_document", _quota_exhausted)

    response = client.post(f"/api/v1/documents/{document.id}/reclassify", json={"category": "price_list"})

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"
    assert response.json()["detail"] == AI_SERVICE_QUOTA_PUBLIC_MESSAGE
    assert "secret-key-value" not in response.text
    assert "Gemini" not in response.text


def test_a_sale_cannot_reclassify(db_session, sale, document):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: sale
    try:
        response = TestClient(app).post(f"/api/v1/documents/{document.id}/reclassify", json={"category": "price_list"})
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()
