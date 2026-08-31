from __future__ import annotations

from contextlib import nullcontext

import pytest
from google.genai import errors as genai_errors

from backend.core.enums import (
    DocumentCategory,
    DocumentReviewStatus,
    DocumentStatus,
    DocumentVisibility,
    LegalStatus,
    UserRole,
)
from backend.models.document import Document
from backend.models.project import Project
from backend.models.user import User
from backend.routers import documents as documents_router
from backend.schemas.document_reclassification import (
    ReclassificationApplyItem,
    ReclassificationApplyRequest,
)
from backend.services.document_classification_service import DocumentClassification
from backend.services.ingestion_service import AI_SERVICE_QUOTA_PUBLIC_MESSAGE, ConflictScanOutcome
from backend.services.legacy_reclassification_service import (
    InvalidConfirmationTokenError,
    LegacyReclassificationError,
    apply_document_reclassification,
    list_reclassification_candidates,
    preview_document_reclassification,
)
from backend.services.parser_service import ParsedSection


@pytest.fixture
def admin(db_session):
    row = User(
        username="backfill-admin",
        email="backfill-admin@example.com",
        hashed_password="x",
        role=UserRole.ADMIN,
    )
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _document(db_session, admin, **overrides) -> Document:
    values = {
        "title": "Beverly_ThongTinDuAn.pdf",
        "file_path": "documents/7/source.pdf",
        "status": DocumentStatus.COMPLETED,
        "visibility": DocumentVisibility.INTERNAL,
        "category": DocumentCategory.SUBDIVISION_INFO,
        "review_status": DocumentReviewStatus.APPROVED,
        "legal_status": LegalStatus.UNKNOWN,
        "is_current": True,
        "uploaded_by": admin.id,
    }
    values.update(overrides)
    row = Document(**values)
    db_session.add(row)
    db_session.commit()
    db_session.refresh(row)
    return row


def _classifier_result(**overrides) -> DocumentClassification:
    values = {
        "category": DocumentCategory.SUBDIVISION_INFO,
        "subcategory": "project_overview",
        "subdivision_names": ["The Beverly"],
        "document_summary": "Thong tin tong quan phan khu The Beverly.",
        "legal_status": LegalStatus.UNKNOWN,
        "confidence": 0.96,
        "reason": "Tieu de va noi dung mo ta tong quan phan khu.",
        "requires_admin_review": False,
    }
    values.update(overrides)
    return DocumentClassification(**values)


def _mock_source(monkeypatch, service, classification=None):
    monkeypatch.setattr(service, "_read_original_file", lambda _path: b"stored-original")
    monkeypatch.setattr(
        service,
        "parse_document",
        lambda _title, _data: [ParsedSection(text="Thong tin tong quan The Beverly", page=1)],
    )
    monkeypatch.setattr(service, "classify_document", lambda _title, _text: classification or _classifier_result())


def test_legacy_candidate_selector_uses_persisted_version(db_session, admin):
    legacy = _document(db_session, admin, classification_version=None)
    current_v3 = _document(
        db_session,
        admin,
        title="new.pdf",
        classification_version="llm-v3-grounded-facts",
        conflict_facts=[],
    )
    incomplete = _document(
        db_session,
        admin,
        title="incomplete-current.pdf",
        classification_version="llm-v3-grounded-facts",
        conflict_facts=None,
    )
    older_llm = _document(
        db_session,
        admin,
        title="llm-v1.pdf",
        classification_version="llm-v1",
        conflict_facts=None,
    )
    _document(db_session, admin, title="failed.pdf", status=DocumentStatus.FAILED, classification_version=None)

    rows = list_reclassification_candidates(db_session, legacy_only=True)

    assert [row.document_id for row in rows] == [legacy.id, current_v3.id, incomplete.id, older_llm.id]


def test_pending_candidate_selector_only_returns_completed_unreviewed_documents(db_session, admin):
    pending = _document(
        db_session,
        admin,
        title="pending-current.pdf",
        review_status=DocumentReviewStatus.PENDING,
        classification_version="llm-v3-grounded-facts",
        conflict_facts=[],
        is_current=False,
    )
    _document(db_session, admin, title="approved.pdf", review_status=DocumentReviewStatus.APPROVED)
    _document(
        db_session,
        admin,
        title="blocked-pending.pdf",
        status=DocumentStatus.BLOCKED,
        review_status=DocumentReviewStatus.PENDING,
        is_current=False,
    )

    rows = list_reclassification_candidates(
        db_session,
        legacy_only=False,
        pending_only=True,
    )

    assert [row.document_id for row in rows] == [pending.id]


def test_preview_is_read_only_and_recommends_exact_subdivision_project(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    project = Project(id="the-beverly", name="The Beverly - Vinhomes Ocean Park")
    sibling = Project(
        id="the-london",
        name="The London - Vinhomes Ocean Park",
        details={"project": {"id": "the-metropolitan", "name": "The Metropolitan"}},
    )
    db_session.add_all([project, sibling])
    document = _document(db_session, admin, category=DocumentCategory.LEGAL_DOCUMENT, project_id=None)
    _mock_source(
        monkeypatch,
        service,
        _classifier_result(
            project_id="the-beverly",
            subdivision_names=["The Beverly", "The Metropolitan"],
        ),
    )

    result = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)

    assert result.error is None
    assert result.confirmation_token
    assert result.suggestion["category"] == DocumentCategory.SUBDIVISION_INFO
    assert result.project_resolution.recommended_project_id == project.id
    assert result.project_resolution.requires_confirmation is True
    assert [candidate.project_id for candidate in result.project_resolution.candidates] == [project.id]
    db_session.refresh(document)
    assert document.category == DocumentCategory.LEGAL_DOCUMENT
    assert document.project_id is None
    assert document.classification_version is None


def test_preview_reports_quota_without_leaking_provider_details(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(db_session, admin)
    _mock_source(monkeypatch, service)
    provider_error = genai_errors.ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "quota error containing secret-key-value",
            }
        },
    )
    monkeypatch.setattr(
        service,
        "classify_document",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(provider_error),
    )

    result = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)

    assert result.error == AI_SERVICE_QUOTA_PUBLIC_MESSAGE
    assert "secret-key-value" not in result.error
    assert "Gemini" not in result.error


def test_tampered_confirmation_token_is_rejected(db_session, admin):
    with pytest.raises(InvalidConfirmationTokenError, match="Invalid"):
        apply_document_reclassification(
            db_session,
            item=ReclassificationApplyItem(confirmation_token="x" * 40 + ".bad"),
            admin_id=admin.id,
        )


def test_apply_rejects_preview_after_metadata_changed(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(db_session, admin)
    _mock_source(monkeypatch, service)
    preview = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)
    document.classification_reason = "Admin changed this after preview"
    db_session.commit()

    with pytest.raises(InvalidConfirmationTokenError, match="changed after preview"):
        apply_document_reclassification(
            db_session,
            item=ReclassificationApplyItem(confirmation_token=preview.confirmation_token),
            admin_id=admin.id,
        )


def test_apply_updates_metadata_and_preserves_active_state(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(db_session, admin, classification_version=None)
    classification = _classifier_result(building_codes=["be1"], requires_admin_review=True)
    _mock_source(monkeypatch, service, classification)
    vector_updates = []
    monkeypatch.setattr(
        service, "update_document_vector_metadata", lambda *args, **kwargs: vector_updates.append(kwargs)
    )
    monkeypatch.setattr(service, "_conflict_scope_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(
        service,
        "scan_conflicts_for",
        lambda *_args, **_kwargs: ConflictScanOutcome(),
    )

    preview = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)
    result = apply_document_reclassification(
        db_session,
        item=ReclassificationApplyItem(confirmation_token=preview.confirmation_token),
        admin_id=admin.id,
    )

    assert result.reindexed is False
    assert result.is_current is True
    assert [call["is_current"] for call in vector_updates] == [False, True]
    db_session.refresh(document)
    assert document.building_codes == ["BE1"]
    assert document.classification_version == "llm-v4-multisection"
    assert document.classification_requires_admin_review is True
    assert document.review_status == DocumentReviewStatus.APPROVED
    assert document.reviewed_by == admin.id
    assert document.classified_at.microsecond == 0
    assert document.reviewed_at.microsecond == 0


def test_admin_apply_activates_document_that_only_awaited_review(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(
        db_session,
        admin,
        classification_version=None,
        review_status=DocumentReviewStatus.PENDING,
        is_current=False,
    )
    _mock_source(monkeypatch, service)
    vector_updates = []
    monkeypatch.setattr(
        service, "update_document_vector_metadata", lambda *args, **kwargs: vector_updates.append(kwargs)
    )
    monkeypatch.setattr(service, "_conflict_scope_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service, "scan_conflicts_for", lambda *_args, **_kwargs: ConflictScanOutcome())
    deleted_vectors = []
    indexed_documents = []
    monkeypatch.setattr(service, "delete_document_vectors", lambda document_id: deleted_vectors.append(document_id))
    monkeypatch.setattr(
        service,
        "_embed_and_index",
        lambda indexed_document, _chunks, *, is_current: indexed_documents.append((indexed_document.id, is_current)),
    )

    preview = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)
    result = apply_document_reclassification(
        db_session,
        item=ReclassificationApplyItem(confirmation_token=preview.confirmation_token),
        admin_id=admin.id,
    )

    assert result.reindexed is True
    assert result.is_current is True
    assert deleted_vectors == [document.id]
    assert indexed_documents == [(document.id, False)]
    assert vector_updates[-1]["is_current"] is True
    db_session.refresh(document)
    assert document.review_status == DocumentReviewStatus.APPROVED
    assert document.classification_version == "llm-v4-multisection"


def test_retry_activates_approved_document_left_quarantined_by_partial_apply(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(
        db_session,
        admin,
        classification_version=None,
        review_status=DocumentReviewStatus.APPROVED,
        is_current=False,
    )
    _mock_source(monkeypatch, service)
    vector_updates = []
    monkeypatch.setattr(
        service, "update_document_vector_metadata", lambda *args, **kwargs: vector_updates.append(kwargs)
    )
    monkeypatch.setattr(service, "_conflict_scope_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service, "scan_conflicts_for", lambda *_args, **_kwargs: ConflictScanOutcome())

    preview = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)
    result = apply_document_reclassification(
        db_session,
        item=ReclassificationApplyItem(confirmation_token=preview.confirmation_token),
        admin_id=admin.id,
    )

    assert result.is_current is True
    assert vector_updates[-1]["is_current"] is True
    db_session.refresh(document)
    assert document.classification_version == "llm-v4-multisection"


def test_blocked_document_never_becomes_current(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(
        db_session,
        admin,
        status=DocumentStatus.BLOCKED,
        review_status=DocumentReviewStatus.REJECTED,
        is_current=False,
    )
    _mock_source(monkeypatch, service)
    vector_updates = []
    monkeypatch.setattr(
        service, "update_document_vector_metadata", lambda *args, **kwargs: vector_updates.append(kwargs)
    )
    monkeypatch.setattr(
        service,
        "scan_conflicts_for",
        lambda *_args, **_kwargs: pytest.fail("blocked documents must not be conflict-scanned or activated"),
    )

    preview = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)
    result = apply_document_reclassification(
        db_session,
        item=ReclassificationApplyItem(confirmation_token=preview.confirmation_token),
        admin_id=admin.id,
    )

    assert result.status == DocumentStatus.BLOCKED
    assert result.is_current is False
    assert vector_updates[-1]["is_current"] is False
    db_session.refresh(document)
    assert document.review_status == DocumentReviewStatus.REJECTED


def test_apply_endpoint_clears_cache_before_attempt_and_after_failure(db_session, admin, monkeypatch):
    events = []
    monkeypatch.setattr(documents_router, "_clear_answer_cache", lambda: events.append("cache-cleared"))

    def fail_before_phase_one(*_args, **_kwargs):
        events.append("apply-started")
        raise LegacyReclassificationError("provider unavailable")

    monkeypatch.setattr(documents_router, "apply_document_reclassification", fail_before_phase_one)
    payload = ReclassificationApplyRequest(
        confirmation="APPLY_LLM_RECLASSIFICATION",
        items=[{"confirmation_token": "x" * 40}],
    )

    response = documents_router.apply_llm_reclassification(payload, db_session, admin)

    assert response.failed == 1
    assert events == ["cache-cleared", "apply-started", "cache-cleared"]


def test_reindex_failure_keeps_legacy_version_and_quarantine(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(
        db_session,
        admin,
        category=DocumentCategory.LEGAL_DOCUMENT,
        classification_version=None,
    )
    _mock_source(monkeypatch, service, _classifier_result())
    monkeypatch.setattr(service, "update_document_vector_metadata", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(service, "chunk_sections_by_classification", lambda *_args, **_kwargs: [object()])
    monkeypatch.setattr(service, "delete_document_vectors", lambda _id: (_ for _ in ()).throw(RuntimeError("qdrant")))

    preview = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)
    with pytest.raises(RuntimeError, match="qdrant"):
        apply_document_reclassification(
            db_session,
            item=ReclassificationApplyItem(confirmation_token=preview.confirmation_token),
            admin_id=admin.id,
        )

    db_session.expire_all()
    stored = db_session.get(Document, document.id)
    assert stored.is_current is False
    assert stored.category == DocumentCategory.LEGAL_DOCUMENT
    assert stored.classification_version is None


def test_concurrent_metadata_change_after_quarantine_is_not_overwritten(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(db_session, admin, classification_version=None)
    _mock_source(monkeypatch, service)
    vector_updates = []
    monkeypatch.setattr(
        service, "update_document_vector_metadata", lambda *args, **kwargs: vector_updates.append(kwargs)
    )

    preview = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)
    original_get_document = service.get_document
    lock_reads = 0

    def racing_get_document(db, document_id, *, for_update=False):
        nonlocal lock_reads
        row = original_get_document(db, document_id, for_update=for_update)
        if for_update:
            lock_reads += 1
        if for_update and lock_reads == 2:
            row.classification_reason = "Concurrent Admin edit"
            db.commit()
        return row

    monkeypatch.setattr(service, "get_document", racing_get_document)

    with pytest.raises(InvalidConfirmationTokenError, match="being quarantined"):
        apply_document_reclassification(
            db_session,
            item=ReclassificationApplyItem(confirmation_token=preview.confirmation_token),
            admin_id=admin.id,
        )

    db_session.expire_all()
    stored = db_session.get(Document, document.id)
    assert stored.classification_reason == "Concurrent Admin edit"
    assert stored.is_current is False
    assert stored.classification_version is None
    assert [call["is_current"] for call in vector_updates] == [False]


def test_final_publish_never_overwrites_a_later_quarantine(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(db_session, admin, classification_version=None)
    _mock_source(monkeypatch, service)
    vector_updates = []
    monkeypatch.setattr(
        service, "update_document_vector_metadata", lambda *args, **kwargs: vector_updates.append(kwargs)
    )
    monkeypatch.setattr(service, "_conflict_scope_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service, "scan_conflicts_for", lambda *_args, **_kwargs: ConflictScanOutcome())

    preview = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)
    original_get_document = service.get_document
    lock_reads = 0

    def quarantine_before_final_publish(db, document_id, *, for_update=False):
        nonlocal lock_reads
        row = original_get_document(db, document_id, for_update=for_update)
        if for_update:
            lock_reads += 1
        if for_update and lock_reads == 4:
            row.is_current = False
            db.commit()
        return row

    monkeypatch.setattr(service, "get_document", quarantine_before_final_publish)

    with pytest.raises(InvalidConfirmationTokenError, match="before vector synchronisation"):
        apply_document_reclassification(
            db_session,
            item=ReclassificationApplyItem(confirmation_token=preview.confirmation_token),
            admin_id=admin.id,
        )

    db_session.expire_all()
    stored = db_session.get(Document, document.id)
    assert stored.is_current is False
    assert stored.classification_version is None
    assert [call["is_current"] for call in vector_updates] == [False]


def test_final_vector_failure_does_not_mark_backfill_complete(db_session, admin, monkeypatch):
    from backend.services import legacy_reclassification_service as service

    document = _document(db_session, admin, classification_version=None)
    _mock_source(monkeypatch, service)
    monkeypatch.setattr(service, "_conflict_scope_lock", lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(service, "scan_conflicts_for", lambda *_args, **_kwargs: ConflictScanOutcome())
    calls = 0

    def fail_final_sync(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("final qdrant sync failed")

    monkeypatch.setattr(service, "update_document_vector_metadata", fail_final_sync)
    preview = preview_document_reclassification(db_session, document_id=document.id, admin_id=admin.id)

    with pytest.raises(RuntimeError, match="final qdrant"):
        apply_document_reclassification(
            db_session,
            item=ReclassificationApplyItem(confirmation_token=preview.confirmation_token),
            admin_id=admin.id,
        )

    db_session.expire_all()
    stored = db_session.get(Document, document.id)
    assert stored.classification_version is None
