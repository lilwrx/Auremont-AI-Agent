"""Xóa tài liệu phải xóa cả vector.

Retrieval đọc Qdrant, không đọc MySQL. Xóa row mà để lại chunk nghĩa là Agent vẫn
báo giá theo bảng giá Admin tưởng đã gỡ, kèm citation trỏ tới `document_id` không
còn tồn tại.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.user import User
from backend.repositories.document import create_document, get_document
from backend.routers import documents as documents_router
from backend.schemas.document import DocumentCreate
from backend.services.vector_store_service import VectorStoreError


@pytest.fixture
def admin(db_session):
    user = User(username="adm1", email="a@x.com", hashed_password="x", role=UserRole.ADMIN)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def deleted_vectors(monkeypatch):
    """Ghi lại document_id đã được yêu cầu xóa khỏi Qdrant."""
    calls: list[int] = []
    monkeypatch.setattr(documents_router, "delete_document_vectors", calls.append)
    return calls


@pytest.fixture
def client(db_session, admin, deleted_vectors):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_deleting_a_document_also_deletes_its_vectors(client, db_session, deleted_vectors):
    document = create_document(db_session, DocumentCreate(title="Bảng giá cũ"))

    assert client.delete(f"/api/v1/documents/{document.id}").status_code == 204

    assert deleted_vectors == [document.id]
    assert get_document(db_session, document.id) is None


def test_document_survives_when_the_vector_store_is_down(client, db_session, monkeypatch):
    """Thà giữ lại row để Admin bấm xóa lần nữa, còn hơn để vector mồ côi vĩnh viễn."""
    document = create_document(db_session, DocumentCreate(title="Bảng giá cũ"))

    def explode(_document_id: int) -> None:
        raise VectorStoreError("Qdrant unreachable")

    monkeypatch.setattr(documents_router, "delete_document_vectors", explode)

    assert client.delete(f"/api/v1/documents/{document.id}").status_code == 503
    assert get_document(db_session, document.id) is not None


def test_deleting_an_unknown_document_returns_404(client, deleted_vectors):
    assert client.delete("/api/v1/documents/9999").status_code == 404
    assert deleted_vectors == []
