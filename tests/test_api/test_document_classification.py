"""Admin duyệt metadata tài liệu dự án."""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import (
    ConflictStatus,
    DocumentCategory,
    DocumentReviewStatus,
    DocumentStatus,
    LegalStatus,
    UserRole,
)
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.conflict_flag import ConflictFlag
from backend.models.document import Document
from backend.models.project import Project
from backend.models.user import User
from backend.repositories.document import create_document
from backend.routers import documents as documents_router
from backend.schemas.document import DocumentCreate
from backend.services import ingestion_service, vector_store_service
from backend.services.parser_service import ParsedSection
from backend.services.vector_store_service import VectorStoreError


@pytest.fixture
def admin(db_session):
    user = User(
        username="admin1",
        email="admin@example.com",
        hashed_password="x",
        role=UserRole.ADMIN,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sale(db_session):
    user = User(
        username="sale1",
        email="sale@example.com",
        hashed_password="x",
        role=UserRole.SALE,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(db_session, admin, monkeypatch):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: admin
    vector_sync_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        vector_store_service,
        "update_document_vector_metadata",
        lambda *args, **kwargs: vector_sync_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(documents_router, "clear_cache", lambda: None)
    monkeypatch.setattr(ingestion_service, "_read_original_file", lambda _key: b"stored-file")
    monkeypatch.setattr(
        ingestion_service,
        "parse_document",
        lambda _title, _data: [ParsedSection(text="Nội dung kiểm thử hợp lệ.", page=1)],
    )
    monkeypatch.setattr(ingestion_service, "delete_document_vectors", lambda _document_id: None)
    monkeypatch.setattr(ingestion_service, "_embed_and_index", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        ingestion_service,
        "scan_conflicts_for",
        lambda *_args, **_kwargs: ingestion_service.ConflictScanOutcome(),
    )
    monkeypatch.setattr(
        ingestion_service,
        "update_document_vector_metadata",
        lambda *args, **kwargs: vector_sync_calls.append((args, kwargs)),
    )

    test_client = TestClient(app)
    test_client.vector_sync_calls = vector_sync_calls
    yield test_client

    app.dependency_overrides.clear()


def test_metadata_list_returns_every_ingested_document(
    client,
    db_session,
    admin,
):
    pending = create_document(
        db_session,
        DocumentCreate(title="CSBH The Beverly T8.pdf", category=DocumentCategory.SALES_POLICY),
        uploaded_by=admin.id,
    )
    pending.status = DocumentStatus.COMPLETED

    approved = create_document(
        db_session,
        DocumentCreate(title="Bang gia The Beverly T8.pdf"),
        uploaded_by=admin.id,
    )
    approved.status = DocumentStatus.COMPLETED
    approved.review_status = DocumentReviewStatus.APPROVED
    processing = create_document(
        db_session,
        DocumentCreate(title="Dang ingest.pdf"),
        uploaded_by=admin.id,
    )
    processing.status = DocumentStatus.PROCESSING
    db_session.commit()

    response = client.get("/api/v1/documents/metadata-editable")

    assert response.status_code == 200, response.text

    document_ids = [item["id"] for item in response.json()]
    assert pending.id in document_ids
    assert approved.id in document_ids
    assert processing.id not in document_ids


def test_upload_rejects_unknown_project_before_creating_document(client, db_session):
    before = db_session.query(Document).count()

    response = client.post(
        "/api/v1/documents/upload",
        data={"project_id": "project-does-not-exist"},
        files={"file": ("metadata.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]
    assert db_session.query(Document).count() == before


def test_upload_reports_ai_quota_as_actionable_service_unavailable(client, monkeypatch):
    from backend.services.ingestion_service import (
        AI_SERVICE_QUOTA_PUBLIC_MESSAGE,
        DocumentAIQuotaExceededError,
    )

    def quota_exhausted(*_args, **_kwargs):
        try:
            raise RuntimeError("provider payload with secret-key-value")
        except RuntimeError as exc:
            raise DocumentAIQuotaExceededError() from exc

    monkeypatch.setattr(documents_router, "ingest_uploaded_document", quota_exhausted)

    response = client.post(
        "/api/v1/documents/upload",
        files={"file": ("metadata.pdf", b"%PDF-1.4\n", "application/pdf")},
    )

    assert response.status_code == 503
    assert response.headers["retry-after"] == "60"
    assert response.json()["detail"] == AI_SERVICE_QUOTA_PUBLIC_MESSAGE
    assert "secret-key-value" not in response.text
    assert "Gemini" not in response.text


def test_admin_document_catalog_includes_projects_without_marketing_details(client, db_session):
    db_session.add(Project(id="internal-project", name="Internal Project", details=None))
    db_session.commit()

    response = client.get("/api/v1/documents/project-catalog")

    assert response.status_code == 200, response.text
    assert {item["id"] for item in response.json()} >= {"internal-project"}


def test_admin_can_approve_project_document_classification(
    client,
    db_session,
    admin,
):
    document = create_document(
        db_session,
        DocumentCreate(
            title="CSBH The Beverly T8.pdf",
            file_path="documents/test/csbh.pdf",
            category=DocumentCategory.SALES_POLICY,
            subdivision_names=["The Beverly"],
            building_codes=["BE1", "BE2"],
            unit_types=["1PN+", "2PN", "3PN"],
        ),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    document.is_current = False
    document.classification_requires_admin_review = True
    db_session.commit()

    response = client.patch(
        f"/api/v1/documents/{document.id}/classification",
        json={
            "category": "sales_policy",
            "subcategory": "standard_policy",
            "subdivision_names": ["The Beverly"],
            "building_codes": ["BE1", "BE2"],
            "unit_types": ["1PN+", "2PN", "3PN"],
            "applicable_area": "Ocean Park 3",
            "document_summary": ("Chính sách bán hàng tháng 08/2026 cho phân khu The Beverly."),
            "version_label": "Tháng 08/2026",
            "effective_date": "2026-08-01",
            "expiry_date": "2026-08-31",
            "applicable_period": "08/2026",
            "legal_status": "unknown",
        },
    )

    assert response.status_code == 200, response.text

    body = response.json()
    assert body["category"] == DocumentCategory.SALES_POLICY
    assert body["review_status"] == DocumentReviewStatus.APPROVED
    assert body["subdivision_names"] == ["The Beverly"]
    assert body["building_codes"] == ["BE1", "BE2"]
    assert body["unit_types"] == ["1PN+", "2PN", "3PN"]
    assert body["effective_date"] == "2026-08-01"
    assert body["reviewed_by"] == admin.id
    assert body["reviewed_at"] is not None
    assert body["is_current"] is True
    assert [metadata["is_current"] for _args, metadata in client.vector_sync_calls] == [True]


def test_classification_approval_preserves_conflict_quarantine(
    client,
    db_session,
    admin,
):
    document = create_document(
        db_session,
        DocumentCreate(
            title="CSBH can Admin chon.pdf",
            file_path="documents/test/conflict.pdf",
            category=DocumentCategory.SALES_POLICY,
        ),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    document.is_current = False
    sibling = create_document(
        db_session,
        DocumentCreate(title="CSBH đang mâu thuẫn.pdf", category=DocumentCategory.SALES_POLICY),
        uploaded_by=admin.id,
    )
    sibling.status = DocumentStatus.COMPLETED
    sibling.review_status = DocumentReviewStatus.APPROVED
    db_session.add(
        ConflictFlag(
            document_id_a=document.id,
            document_id_b=sibling.id,
            status=ConflictStatus.OPEN,
        )
    )
    db_session.commit()

    response = client.patch(
        f"/api/v1/documents/{document.id}/classification",
        json={"category": "sales_policy", "legal_status": "unknown"},
    )

    assert response.status_code == 200, response.text
    assert client.vector_sync_calls[-1][1]["is_current"] is False


def test_metadata_can_be_edited_more_than_once(client, db_session, admin):
    """There is no one-shot approval step, so a correction can itself be corrected."""
    document = create_document(
        db_session,
        DocumentCreate(title="CSBH da duyet.pdf", category=DocumentCategory.SALES_POLICY),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    document.review_status = DocumentReviewStatus.APPROVED
    db_session.commit()
    payload = {"category": "sales_policy", "legal_status": "unknown"}

    first = client.patch(f"/api/v1/documents/{document.id}/classification", json=payload)
    second = client.patch(f"/api/v1/documents/{document.id}/classification", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200


def test_processing_document_cannot_be_approved_or_activated(client, db_session, admin):
    document = create_document(
        db_session,
        DocumentCreate(title="CSBH dang xu ly.pdf", category=DocumentCategory.SALES_POLICY),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.PROCESSING
    db_session.commit()

    response = client.patch(
        f"/api/v1/documents/{document.id}/classification",
        json={"category": "sales_policy"},
    )

    assert response.status_code == 409
    assert client.vector_sync_calls == []


@pytest.mark.parametrize(
    ("initial", "payload"),
    [
        (
            DocumentCreate(title="Sai category.pdf", category=DocumentCategory.OTHER),
            {"category": "price_list"},
        ),
        (
            DocumentCreate(
                title="Sai scope.pdf",
                category=DocumentCategory.PRICE_LIST,
                building_codes=["BE1"],
            ),
            {"category": "price_list", "building_codes": ["ZU1"]},
        ),
    ],
)
def test_structural_classification_changes_require_controlled_reindex_or_rescan(
    client,
    db_session,
    admin,
    initial,
    payload,
):
    document = create_document(db_session, initial, uploaded_by=admin.id)
    document.status = DocumentStatus.COMPLETED
    document.is_current = False
    db_session.commit()

    response = client.patch(f"/api/v1/documents/{document.id}/classification", json=payload)

    assert response.status_code == 409
    db_session.expire_all()
    stored = db_session.get(type(document), document.id)
    assert stored.review_status == DocumentReviewStatus.PENDING
    assert client.vector_sync_calls == []


def test_controlled_correction_accepts_live_project_category_and_scope(
    client,
    db_session,
    admin,
    monkeypatch,
):
    project = Project(id="the-beverly", name="The Beverly")
    db_session.add(project)
    document = create_document(
        db_session,
        DocumentCreate(title="Can Admin sua scope.pdf", category=DocumentCategory.OTHER),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()
    captured: dict[str, object] = {}

    def controlled_correction(db, *, document_id, category, reviewed_by, metadata_updates):
        captured.update(
            document_id=document_id,
            category=category,
            reviewed_by=reviewed_by,
            metadata_updates=metadata_updates,
        )
        document.category = category
        document.project_id = metadata_updates["project_id"]
        document.subdivision_names = metadata_updates["subdivision_names"]
        document.review_status = DocumentReviewStatus.APPROVED
        return document

    monkeypatch.setattr(documents_router, "reclassify_document", controlled_correction)

    response = client.post(
        f"/api/v1/documents/{document.id}/reclassify",
        json={
            "category": "price_list",
            "project_id": "the-beverly",
            "subdivision_names": ["The Beverly"],
            "building_codes": ["BE1"],
            "unit_types": ["2PN"],
        },
    )

    assert response.status_code == 200, response.text
    assert captured["category"] == DocumentCategory.PRICE_LIST
    assert captured["reviewed_by"] == admin.id
    assert captured["metadata_updates"] == {
        "project_id": "the-beverly",
        "subdivision_names": ["The Beverly"],
        "building_codes": ["BE1"],
        "unit_types": ["2PN"],
    }


def test_controlled_correction_rejects_stale_project_before_starting(
    client,
    db_session,
    admin,
    monkeypatch,
):
    document = create_document(
        db_session,
        DocumentCreate(title="Sai project.pdf", category=DocumentCategory.OTHER),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()
    called = False

    def should_not_start(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("controlled correction must not start")

    monkeypatch.setattr(documents_router, "reclassify_document", should_not_start)

    response = client.post(
        f"/api/v1/documents/{document.id}/reclassify",
        json={"category": "other", "project_id": "deleted-project"},
    )

    assert response.status_code == 422
    assert called is False


def test_classification_patch_preserves_omitted_suggested_metadata(client, db_session, admin):
    document = create_document(
        db_session,
        DocumentCreate(
            title="CSBH giu metadata.pdf",
            file_path="documents/test/preserve.pdf",
            category=DocumentCategory.SALES_POLICY,
            building_codes=["BE1"],
            version_label="V2",
        ),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()

    response = client.patch(
        f"/api/v1/documents/{document.id}/classification",
        json={"category": "sales_policy"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["building_codes"] == ["BE1"]
    assert response.json()["version_label"] == "V2"


def test_classification_index_failure_keeps_pending_document_unapproved(
    client,
    db_session,
    admin,
    monkeypatch,
):
    document = create_document(
        db_session,
        DocumentCreate(
            title="CSBH rollback.pdf",
            file_path="documents/test/rollback.pdf",
            category=DocumentCategory.SALES_POLICY,
        ),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()

    def fail_index(*_args, **_kwargs):
        raise VectorStoreError("Qdrant unavailable")

    monkeypatch.setattr(ingestion_service, "_embed_and_index", fail_index)

    response = client.patch(
        f"/api/v1/documents/{document.id}/classification",
        json={"category": "sales_policy"},
    )

    assert response.status_code == 503
    db_session.expire_all()
    stored = db_session.get(type(document), document.id)
    assert stored.review_status == DocumentReviewStatus.PENDING
    assert stored.is_current is False
    assert client.vector_sync_calls[-1][1]["review_status"] == DocumentReviewStatus.PENDING
    assert client.vector_sync_calls[-1][1]["is_current"] is False


def test_classification_activation_failure_leaves_approved_document_quarantined(
    client,
    db_session,
    admin,
    monkeypatch,
):
    document = create_document(
        db_session,
        DocumentCreate(
            title="CSBH activation fail.pdf",
            file_path="documents/test/activation.pdf",
            category=DocumentCategory.SALES_POLICY,
        ),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()
    calls: list[bool] = []

    def fail_activation(_document_id, **metadata):
        calls.append(metadata["is_current"])
        if metadata["is_current"]:
            raise VectorStoreError("Qdrant unavailable")

    monkeypatch.setattr(vector_store_service, "update_document_vector_metadata", fail_activation)

    response = client.patch(
        f"/api/v1/documents/{document.id}/classification",
        json={"category": "sales_policy"},
    )

    assert response.status_code == 503
    db_session.expire_all()
    stored = db_session.get(type(document), document.id)
    assert stored.review_status == DocumentReviewStatus.APPROVED
    assert stored.is_current is False
    assert calls == [True, False]


def test_tightening_visibility_updates_qdrant_before_mysql(
    client,
    db_session,
    admin,
    monkeypatch,
):
    document = create_document(
        db_session,
        DocumentCreate(title="Tai lieu cong khai.pdf", visibility="public"),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()
    events: list[str] = []
    original_commit = db_session.commit

    def record_commit():
        events.append("mysql_commit")
        original_commit()

    def record_sync(_document_id, **kwargs):
        events.append("qdrant_sync")
        client.vector_sync_calls.append(((_document_id,), kwargs))

    db_session.commit = record_commit
    monkeypatch.setattr(vector_store_service, "update_document_vector_metadata", record_sync)

    response = client.patch(
        f"/api/v1/documents/{document.id}/visibility",
        json={"visibility": "internal"},
    )

    assert response.status_code == 200, response.text
    assert events == ["qdrant_sync", "mysql_commit"]
    assert client.vector_sync_calls[-1][1]["visibility"] == "internal"
    assert response.json()["visibility"] == "internal"


def test_tightening_visibility_rolls_back_mysql_when_qdrant_fails(
    client,
    db_session,
    admin,
    monkeypatch,
):
    document = create_document(
        db_session,
        DocumentCreate(title="Tai lieu cong khai.pdf", visibility="public"),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()

    def fail_sync(*_args, **_kwargs):
        raise VectorStoreError("Qdrant unavailable")

    monkeypatch.setattr(vector_store_service, "update_document_vector_metadata", fail_sync)

    response = client.patch(
        f"/api/v1/documents/{document.id}/visibility",
        json={"visibility": "internal"},
    )

    assert response.status_code == 503
    db_session.expire_all()
    assert db_session.get(type(document), document.id).visibility == "public"


def test_loosening_visibility_quarantines_then_publishes_fresh_state(
    client,
    db_session,
    admin,
    monkeypatch,
):
    document = create_document(
        db_session,
        DocumentCreate(
            title="Tai lieu noi bo.pdf",
            visibility="internal",
            category=DocumentCategory.INTERNAL_GUIDE,
        ),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    document.review_status = DocumentReviewStatus.APPROVED
    db_session.commit()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        vector_store_service,
        "update_document_vector_metadata",
        lambda _document_id, **metadata: calls.append(metadata),
    )

    response = client.patch(
        f"/api/v1/documents/{document.id}/visibility",
        json={"visibility": "public"},
    )

    assert response.status_code == 200, response.text
    assert [(call["visibility"], call["is_current"]) for call in calls] == [
        ("internal", False),
        ("public", True),
    ]


def test_loosening_visibility_does_not_reactivate_document_blocked_between_phases(
    client,
    db_session,
    admin,
    monkeypatch,
):
    document = create_document(
        db_session,
        DocumentCreate(title="Tai lieu can block.pdf", visibility="internal"),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()
    calls: list[bool] = []
    monkeypatch.setattr(
        vector_store_service,
        "update_document_vector_metadata",
        lambda _document_id, **metadata: calls.append(metadata["is_current"]),
    )
    original_commit = db_session.commit
    commit_count = 0

    def commit_then_simulate_conflict():
        nonlocal commit_count
        original_commit()
        commit_count += 1
        if commit_count == 1:
            current = db_session.get(type(document), document.id)
            current.is_current = False
            original_commit()

    db_session.commit = commit_then_simulate_conflict

    response = client.patch(
        f"/api/v1/documents/{document.id}/visibility",
        json={"visibility": "public"},
    )

    assert response.status_code == 200, response.text
    assert calls == [False, False]
    assert response.json()["is_current"] is False


def test_visibility_change_is_rejected_while_ingestion_is_processing(client, db_session, admin):
    document = create_document(
        db_session,
        DocumentCreate(title="Dang xu ly visibility.pdf"),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.PROCESSING
    db_session.commit()

    response = client.patch(
        f"/api/v1/documents/{document.id}/visibility",
        json={"visibility": "public"},
    )

    assert response.status_code == 409


def test_visibility_change_is_rejected_before_ingestion_starts(client, db_session, admin):
    document = create_document(
        db_session,
        DocumentCreate(title="Chua ingest visibility.pdf"),
        uploaded_by=admin.id,
    )

    response = client.patch(
        f"/api/v1/documents/{document.id}/visibility",
        json={"visibility": "public"},
    )

    assert response.status_code == 409


def test_admin_can_approve_legal_document_classification(
    client,
    db_session,
    admin,
):
    document = create_document(
        db_session,
        DocumentCreate(
            title="Nghi dinh 96 2024 ND CP.pdf",
            file_path="documents/test/legal.pdf",
            category=DocumentCategory.LEGAL_DOCUMENT,
        ),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()

    response = client.patch(
        f"/api/v1/documents/{document.id}/classification",
        json={
            "category": "legal_document",
            "legal_document_type": "Nghị định",
            "legal_document_number": "96/2024/NĐ-CP",
            "legal_issuer": "Chính phủ",
            "legal_domain": "Kinh doanh bất động sản",
            "legal_status": "effective",
        },
    )

    assert response.status_code == 200, response.text

    body = response.json()
    assert body["category"] == DocumentCategory.LEGAL_DOCUMENT
    assert body["legal_document_number"] == "96/2024/NĐ-CP"
    assert body["legal_status"] == LegalStatus.EFFECTIVE
    assert body["review_status"] == DocumentReviewStatus.APPROVED


def test_approving_not_yet_effective_legal_document_keeps_it_quarantined(
    client,
    db_session,
    admin,
):
    document = create_document(
        db_session,
        DocumentCreate(
            title="Nghi dinh tuong lai.pdf",
            file_path="documents/test/future-legal.pdf",
            category=DocumentCategory.LEGAL_DOCUMENT,
        ),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()

    response = client.patch(
        f"/api/v1/documents/{document.id}/classification",
        json={
            "category": "legal_document",
            "legal_status": "not_yet_effective",
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["is_current"] is False
    assert [metadata["is_current"] for _args, metadata in client.vector_sync_calls] == [False]


def test_sale_cannot_approve_document_classification(
    client,
    db_session,
    admin,
    sale,
):
    document = create_document(
        db_session,
        DocumentCreate(title="Tai lieu noi bo.pdf", category=DocumentCategory.INTERNAL_GUIDE),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()

    app.dependency_overrides[get_current_user] = lambda: sale

    response = client.patch(
        f"/api/v1/documents/{document.id}/classification",
        json={
            "category": "internal_guide",
            "legal_status": "unknown",
        },
    )

    assert response.status_code == 403


def test_classifying_an_unknown_document_returns_404(client):
    response = client.patch(
        "/api/v1/documents/999999/classification",
        json={
            "category": "other",
            "legal_status": "unknown",
        },
    )

    assert response.status_code == 404


def test_changing_visibility_clears_the_semantic_cache(client, db_session, admin, monkeypatch):
    """Otherwise a question cached while this document was still internal keeps serving
    that stale answer forever after it goes public — the cache has no idea anything about
    this specific document changed, so the only correct move is clearing all of it."""
    document = create_document(
        db_session,
        DocumentCreate(title="Zurich_VHOP_ThongTinDuAn_Full.pdf"),
        uploaded_by=admin.id,
    )
    document.status = DocumentStatus.COMPLETED
    db_session.commit()
    calls = []
    monkeypatch.setattr(documents_router, "clear_cache", lambda: calls.append("cleared"))

    response = client.patch(
        f"/api/v1/documents/{document.id}/visibility",
        json={"visibility": "public"},
    )

    assert response.status_code == 200, response.text
    assert calls == ["cleared"]


def test_changing_visibility_for_an_unknown_document_returns_404(client):
    response = client.patch(
        "/api/v1/documents/999999/visibility",
        json={"visibility": "public"},
    )

    assert response.status_code == 404
