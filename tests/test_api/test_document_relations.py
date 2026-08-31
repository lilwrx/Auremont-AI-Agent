"""Version relations must retire superseded documents from RAG safely."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from backend.core.deps import get_current_user
from backend.core.enums import DocumentReviewStatus, DocumentStatus, LegalStatus, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.document_relation import DocumentRelation
from backend.models.user import User
from backend.repositories.document import create_document, get_document
from backend.schemas.document import DocumentCreate
from backend.services import vector_store_service
from backend.services.vector_store_service import VectorStoreError


@pytest.fixture
def admin(db_session):
    user = User(username="admin1", email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(db_session, admin, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: admin
    monkeypatch.setattr(vector_store_service, "update_document_vector_metadata", lambda *_args, **_kwargs: None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_approved_replacement_retires_the_old_document(client, db_session):
    old = create_document(db_session, DocumentCreate(title="CSBH tháng 07"))
    new = create_document(db_session, DocumentCreate(title="CSBH tháng 08"))
    old.review_status = DocumentReviewStatus.APPROVED
    new.review_status = DocumentReviewStatus.APPROVED
    old.status = DocumentStatus.COMPLETED
    new.status = DocumentStatus.COMPLETED
    db_session.commit()

    created = client.post(
        "/api/v1/document-relations",
        json={
            "source_document_id": new.id,
            "target_document_id": old.id,
            "relation_type": "replaces",
            "confidence": 0.95,
        },
    )
    assert created.status_code == 201, created.text

    response = client.post(
        f"/api/v1/document-relations/{created.json()['id']}/review",
        json={"approve": True},
    )
    assert response.status_code == 200, response.text
    assert response.json()["review_status"] == "approved"
    assert get_document(db_session, old.id).is_current is False
    assert get_document(db_session, old.id).status == DocumentStatus.BLOCKED
    assert get_document(db_session, new.id).is_current is True


def test_approved_repeal_marks_legal_document_repealed(client, db_session):
    old = create_document(db_session, DocumentCreate(title="Nghị định cũ"))
    new = create_document(db_session, DocumentCreate(title="Nghị định mới"))
    old.legal_status = LegalStatus.EFFECTIVE
    old.status = DocumentStatus.COMPLETED
    old.review_status = DocumentReviewStatus.APPROVED
    new.status = DocumentStatus.COMPLETED
    new.review_status = DocumentReviewStatus.APPROVED
    db_session.commit()

    created = client.post(
        "/api/v1/document-relations",
        json={
            "source_document_id": new.id,
            "target_document_id": old.id,
            "relation_type": "repeals",
        },
    )
    response = client.post(
        f"/api/v1/document-relations/{created.json()['id']}/review",
        json={"approve": True},
    )

    assert response.status_code == 200, response.text
    old = get_document(db_session, old.id)
    assert old.is_current is False
    assert old.legal_status == LegalStatus.REPEALED


def test_relation_cannot_link_a_document_to_itself(client, db_session):
    document = create_document(db_session, DocumentCreate(title="Một tài liệu"))
    response = client.post(
        "/api/v1/document-relations",
        json={
            "source_document_id": document.id,
            "target_document_id": document.id,
            "relation_type": "updates",
        },
    )
    assert response.status_code == 400


def test_vector_failure_rolls_back_relation_review(client, db_session, monkeypatch):
    old = create_document(db_session, DocumentCreate(title="CSBH cũ"))
    new = create_document(db_session, DocumentCreate(title="CSBH mới"))
    old.status = DocumentStatus.COMPLETED
    old.review_status = DocumentReviewStatus.APPROVED
    new.status = DocumentStatus.COMPLETED
    new.review_status = DocumentReviewStatus.APPROVED
    db_session.commit()
    created = client.post(
        "/api/v1/document-relations",
        json={
            "source_document_id": new.id,
            "target_document_id": old.id,
            "relation_type": "replaces",
        },
    )

    def fail_sync(*_args, **_kwargs):
        raise VectorStoreError("Qdrant unavailable")

    monkeypatch.setattr(vector_store_service, "update_document_vector_metadata", fail_sync)

    response = client.post(
        f"/api/v1/document-relations/{created.json()['id']}/review",
        json={"approve": True},
    )

    assert response.status_code == 503
    db_session.expire_all()
    relation = db_session.get(DocumentRelation, created.json()["id"])
    assert relation.review_status == DocumentReviewStatus.PENDING
    assert get_document(db_session, old.id).is_current is True


def test_ineligible_source_cannot_retire_a_current_document(client, db_session):
    target = create_document(db_session, DocumentCreate(title="Tài liệu đang dùng"))
    source = create_document(db_session, DocumentCreate(title="Tài liệu upload lỗi"))
    target.status = DocumentStatus.COMPLETED
    target.review_status = DocumentReviewStatus.APPROVED
    source.status = DocumentStatus.FAILED
    source.review_status = DocumentReviewStatus.REJECTED
    db_session.commit()
    created = client.post(
        "/api/v1/document-relations",
        json={
            "source_document_id": source.id,
            "target_document_id": target.id,
            "relation_type": "replaces",
        },
    )

    response = client.post(
        f"/api/v1/document-relations/{created.json()['id']}/review",
        json={"approve": True},
    )

    assert response.status_code == 400
    db_session.expire_all()
    assert get_document(db_session, target.id).is_current is True


def test_not_yet_effective_source_cannot_retire_current_document(client, db_session):
    target = create_document(db_session, DocumentCreate(title="Tài liệu đang dùng"))
    source = create_document(db_session, DocumentCreate(title="Văn bản chưa hiệu lực"))
    for document in (target, source):
        document.status = DocumentStatus.COMPLETED
        document.review_status = DocumentReviewStatus.APPROVED
    source.legal_status = LegalStatus.NOT_YET_EFFECTIVE
    source.is_current = False
    db_session.commit()
    created = client.post(
        "/api/v1/document-relations",
        json={
            "source_document_id": source.id,
            "target_document_id": target.id,
            "relation_type": "replaces",
        },
    )

    response = client.post(
        f"/api/v1/document-relations/{created.json()['id']}/review",
        json={"approve": True},
    )

    assert response.status_code == 400
    db_session.expire_all()
    assert get_document(db_session, target.id).is_current is True


def test_processing_target_cannot_be_retired_during_ingestion(client, db_session):
    target = create_document(db_session, DocumentCreate(title="Tài liệu đang ingest"))
    source = create_document(db_session, DocumentCreate(title="Tài liệu thay thế"))
    target.status = DocumentStatus.PROCESSING
    target.review_status = DocumentReviewStatus.APPROVED
    source.status = DocumentStatus.COMPLETED
    source.review_status = DocumentReviewStatus.APPROVED
    db_session.commit()
    created = client.post(
        "/api/v1/document-relations",
        json={
            "source_document_id": source.id,
            "target_document_id": target.id,
            "relation_type": "replaces",
        },
    )

    response = client.post(
        f"/api/v1/document-relations/{created.json()['id']}/review",
        json={"approve": True},
    )

    assert response.status_code == 400
    db_session.expire_all()
    assert get_document(db_session, target.id).status == DocumentStatus.PROCESSING


def test_unknown_relation_commit_outcome_keeps_target_quarantined(
    client,
    db_session,
    monkeypatch,
):
    target = create_document(db_session, DocumentCreate(title="Tài liệu cũ"))
    source = create_document(db_session, DocumentCreate(title="Tài liệu mới"))
    for document in (target, source):
        document.status = DocumentStatus.COMPLETED
        document.review_status = DocumentReviewStatus.APPROVED
    db_session.commit()
    created = client.post(
        "/api/v1/document-relations",
        json={
            "source_document_id": source.id,
            "target_document_id": target.id,
            "relation_type": "replaces",
        },
    )
    calls: list[bool] = []
    monkeypatch.setattr(
        vector_store_service,
        "update_document_vector_metadata",
        lambda _document_id, **metadata: calls.append(metadata["is_current"]),
    )
    real_commit = db_session.commit

    def commit_then_lose_ack():
        real_commit()
        raise SQLAlchemyError("lost commit acknowledgement")

    db_session.commit = commit_then_lose_ack

    response = client.post(
        f"/api/v1/document-relations/{created.json()['id']}/review",
        json={"approve": True},
    )

    assert response.status_code == 503
    db_session.expire_all()
    assert db_session.get(DocumentRelation, created.json()["id"]).review_status == DocumentReviewStatus.APPROVED
    assert get_document(db_session, target.id).is_current is False
    assert calls == [False]
