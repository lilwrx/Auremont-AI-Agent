"""Cảnh báo mâu thuẫn: quyết định 'giữ tài liệu nào' của Admin phải được thi hành."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import SQLAlchemyError

from backend.core.deps import get_current_user
from backend.core.enums import (
    ConflictStatus,
    DocumentRelationType,
    DocumentReviewStatus,
    DocumentStatus,
    LegalStatus,
    UserRole,
)
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.conflict_flag import ConflictFlag
from backend.models.document_relation import DocumentRelation
from backend.models.user import User
from backend.repositories.conflict_flag import create_conflict
from backend.repositories.document import create_document, get_document
from backend.schemas.document import DocumentCreate
from backend.services import vector_store_service
from backend.services.document_category_service import document_categories
from backend.services.vector_store_service import VectorStoreError


@pytest.fixture
def admin(db_session):
    user = User(username="adm1", email="a@x.com", hashed_password="x", role=UserRole.ADMIN)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def vector_syncs(monkeypatch):
    """Stand in for Qdrant and record what the router pushed into it.

    Resolving a conflict now mirrors the decision into the vector payload, and there is
    no Qdrant in a unit test run. Recording the calls rather than dropping them keeps the
    assertion available: MySQL saying BLOCKED means nothing if retrieval was never told.
    """
    calls: list[dict] = []
    monkeypatch.setattr(
        vector_store_service,
        "update_document_vector_metadata",
        lambda document_id, **kwargs: calls.append({"document_id": document_id, **kwargs}),
    )
    return calls


@pytest.fixture
def client(db_session, admin, vector_syncs):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def conflict(db_session):
    """Hai bản bảng giá của cùng một dự án, bị flag là mâu thuẫn."""
    old = create_document(db_session, DocumentCreate(title="Bảng giá v1"))
    new = create_document(db_session, DocumentCreate(title="Bảng giá v2"))
    old.status = DocumentStatus.COMPLETED
    new.status = DocumentStatus.COMPLETED
    db_session.commit()
    db_session.refresh(old)
    db_session.refresh(new)
    flag = create_conflict(db_session, document_id_a=old.id, document_id_b=new.id, description="Giá khác nhau")
    return flag, old, new


def test_resolving_keeps_the_chosen_document_and_blocks_the_other(client, db_session, conflict):
    flag, old, new = conflict

    response = client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": new.id})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resolved"
    assert response.json()["severity"] == "medium"

    assert get_document(db_session, new.id).status != DocumentStatus.BLOCKED
    assert get_document(db_session, old.id).status == DocumentStatus.BLOCKED
    assert get_document(db_session, new.id).review_status == DocumentReviewStatus.APPROVED
    assert get_document(db_session, new.id).is_current is True


def test_dismissing_keeps_both_documents_untouched(client, db_session, conflict):
    flag, old, new = conflict
    old_before = get_document(db_session, old.id)
    new_before = get_document(db_session, new.id)
    old_status, old_is_current = old_before.status, old_before.is_current
    new_status, new_is_current = new_before.status, new_before.is_current

    response = client.post(f"/api/v1/admin/conflicts/{flag.id}/dismiss")
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "resolved"
    assert response.json()["resolved_by"] is not None

    assert get_document(db_session, old.id).status == old_status
    assert get_document(db_session, old.id).is_current == old_is_current
    assert get_document(db_session, new.id).status == new_status
    assert get_document(db_session, new.id).is_current == new_is_current


def test_dismissing_an_already_resolved_conflict_is_rejected(client, conflict):
    flag, _old, new = conflict
    first = client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": new.id})
    assert first.status_code == 200

    second = client.post(f"/api/v1/admin/conflicts/{flag.id}/dismiss")
    assert second.status_code == 409


def test_existing_conflict_is_enriched_by_semantic_rescan_and_exposed_by_api(client, db_session, conflict):
    flag, old, new = conflict
    flag.evidence = {
        "rule_signals": ["price_changed"],
        "sources": {"rule": {"unit_code": "OCP1-S1-0203"}},
    }
    db_session.commit()

    enriched = create_conflict(
        db_session,
        document_id_a=new.id,
        document_id_b=old.id,
        description="Hai tài liệu quy định giá bán khác nhau.",
        detection_method="llm",
        confidence=0.94,
        similarity_score=0.82,
        conflict_type="price",
        evidence={
            "facts": [{"fact_key": "unit.price", "document_a": "2.88 tỷ", "document_b": "3.10 tỷ"}],
            "sources": {"llm": {"model": "semantic-judge"}},
        },
        analysis_version="semantic-conflict-v1",
    )

    assert enriched.id == flag.id
    assert db_session.query(ConflictFlag).count() == 1
    assert enriched.detection_method == "hybrid"
    assert enriched.confidence == pytest.approx(0.94)
    assert enriched.similarity_score == pytest.approx(0.82)
    assert enriched.conflict_type == "price"
    assert enriched.analysis_version == "semantic-conflict-v1"
    assert enriched.evidence == {
        "rule_signals": ["price_changed"],
        "facts": [{"fact_key": "unit.price", "document_a": "3.10 tỷ", "document_b": "2.88 tỷ"}],
        "sources": {
            "rule": {"unit_code": "OCP1-S1-0203"},
            "llm": {"model": "semantic-judge"},
        },
    }

    row = client.get("/api/v1/admin/conflicts").json()[0]
    assert row["description"] == "Hai tài liệu quy định giá bán khác nhau."
    assert row["detection_method"] == "hybrid"
    assert row["confidence"] == pytest.approx(0.94)
    assert row["similarity_score"] == pytest.approx(0.82)
    assert row["conflict_type"] == "price"
    assert row["severity"] == "high"
    assert row["analysis_version"] == "semantic-conflict-v1"
    assert row["evidence"] == enriched.evidence


def test_resolved_pair_is_not_reopened_by_a_precomputed_rescan(client, db_session, conflict):
    flag, old, new = conflict
    response = client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": new.id})
    assert response.status_code == 200

    raced = create_conflict(
        db_session,
        document_id_a=new.id,
        document_id_b=old.id,
        description="A stale semantic scan finished after the Admin decision.",
        detection_method="llm",
        confidence=0.99,
        evidence={"semantic": {"evidence": [{"quote_a": "new", "quote_b": "old"}]}},
    )

    assert raced.id == flag.id
    assert raced.status == ConflictStatus.RESOLVED
    assert db_session.query(ConflictFlag).count() == 1
    assert raced.description == "Giá khác nhau"


def test_null_rescan_metadata_does_not_clear_existing_analysis(db_session, conflict):
    flag, old, new = conflict
    enriched = create_conflict(
        db_session,
        old.id,
        new.id,
        "Semantic result",
        detection_method="llm",
        confidence=0.88,
        evidence={"facts": [{"fact_key": "payment.deadline"}]},
    )

    rescanned = create_conflict(
        db_session,
        old.id,
        new.id,
        None,
        detection_method="llm",
        confidence=None,
        evidence=None,
    )

    assert rescanned.id == flag.id == enriched.id
    assert rescanned.detection_method == "hybrid"
    assert rescanned.description == "Semantic result"
    assert rescanned.confidence == pytest.approx(0.88)
    assert rescanned.evidence == {"facts": [{"fact_key": "payment.deadline"}]}


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("confidence", {"confidence": 1.01}),
        ("similarity_score", {"similarity_score": -0.01}),
        ("detection method", {"detection_method": "manual"}),
    ],
)
def test_conflict_analysis_metadata_is_validated(db_session, conflict, field, kwargs):
    _flag, old, new = conflict

    with pytest.raises(ValueError, match=field):
        create_conflict(db_session, old.id, new.id, "Invalid analysis", **kwargs)


def test_rejected_document_is_removed_from_retrieval(client, db_session, conflict, vector_syncs):
    """BLOCKED một mình không đủ: rag_service lọc theo is_current, không nhìn `status`.

    Thiếu bước này, Admin bấm "ưu tiên bản mới" xong bảng giá cũ vẫn tiếp tục
    được dùng để trả lời khách.
    """
    flag, old, new = conflict

    client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": new.id})

    assert get_document(db_session, old.id).is_current is False
    assert get_document(db_session, new.id).is_current is True
    assert vector_syncs == [
        {
            "document_id": old.id,
            "review_status": get_document(db_session, old.id).review_status,
            "legal_status": get_document(db_session, old.id).legal_status,
            "category": get_document(db_session, old.id).category,
            "categories": document_categories(get_document(db_session, old.id)),
            "visibility": get_document(db_session, old.id).visibility,
            "is_current": False,
        },
        {
            "document_id": new.id,
            "review_status": DocumentReviewStatus.APPROVED,
            "legal_status": get_document(db_session, new.id).legal_status,
            "category": get_document(db_session, new.id).category,
            "categories": document_categories(get_document(db_session, new.id)),
            "visibility": get_document(db_session, new.id).visibility,
            "is_current": False,
        },
        {
            "document_id": new.id,
            "review_status": DocumentReviewStatus.APPROVED,
            "legal_status": get_document(db_session, new.id).legal_status,
            "category": get_document(db_session, new.id).category,
            "categories": document_categories(get_document(db_session, new.id)),
            "visibility": get_document(db_session, new.id).visibility,
            "is_current": True,
        },
    ]


def test_the_two_choices_are_not_interchangeable(client, db_session, conflict):
    """Giữ tài liệu A phải chặn B — ngược hẳn với lựa chọn kia."""
    flag, old, new = conflict

    client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": old.id})

    assert get_document(db_session, old.id).status != DocumentStatus.BLOCKED
    assert get_document(db_session, new.id).status == DocumentStatus.BLOCKED


def test_resolved_conflict_leaves_the_open_list(client, conflict):
    flag, _old, new = conflict
    assert [c["id"] for c in client.get("/api/v1/admin/conflicts").json()] == [flag.id]

    client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": new.id})

    assert client.get("/api/v1/admin/conflicts").json() == []


def test_rejects_a_document_outside_the_conflict(client, db_session, conflict):
    """Nếu không kiểm, quyết định của Admin sẽ áp lên nhầm tài liệu."""
    flag, old, new = conflict
    unrelated = create_document(db_session, DocumentCreate(title="Tài liệu không liên quan"))

    response = client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": unrelated.id})
    assert response.status_code == 400

    assert get_document(db_session, old.id).status != DocumentStatus.BLOCKED
    assert get_document(db_session, new.id).status != DocumentStatus.BLOCKED
    assert [c["id"] for c in client.get("/api/v1/admin/conflicts").json()] == [flag.id]


def test_unknown_conflict_returns_404(client, conflict):
    _flag, _old, new = conflict
    assert client.post("/api/v1/admin/conflicts/9999/resolve", json={"keep_document_id": new.id}).status_code == 404


def test_resolving_an_already_closed_conflict_returns_409(client, conflict):
    flag, _old, new = conflict

    assert (
        client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": new.id}).status_code == 200
    )
    assert (
        client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": new.id}).status_code == 409
    )


def test_retired_document_cannot_be_reactivated_as_conflict_winner(client, db_session, conflict):
    flag, old, new = conflict
    old.is_current = False
    db_session.add(
        DocumentRelation(
            source_document_id=new.id,
            target_document_id=old.id,
            relation_type=DocumentRelationType.REPLACES,
            review_status=DocumentReviewStatus.APPROVED,
        )
    )
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/conflicts/{flag.id}/resolve",
        json={"keep_document_id": old.id},
    )

    assert response.status_code == 409
    db_session.expire_all()
    assert db_session.get(type(flag), flag.id).status == ConflictStatus.OPEN
    assert get_document(db_session, old.id).is_current is False


def test_not_yet_effective_document_cannot_win_conflict(client, db_session, conflict):
    flag, _old, new = conflict
    new.legal_status = LegalStatus.NOT_YET_EFFECTIVE
    new.is_current = False
    db_session.commit()

    response = client.post(
        f"/api/v1/admin/conflicts/{flag.id}/resolve",
        json={"keep_document_id": new.id},
    )

    assert response.status_code == 409
    db_session.expire_all()
    assert db_session.get(type(flag), flag.id).status == ConflictStatus.OPEN
    assert get_document(db_session, new.id).is_current is False


def test_vector_failure_rolls_back_the_mysql_resolution(client, db_session, conflict, monkeypatch):
    flag, old, new = conflict

    def fail_vector_sync(*_args, **_kwargs):
        raise VectorStoreError("Qdrant unavailable")

    monkeypatch.setattr(vector_store_service, "update_document_vector_metadata", fail_vector_sync)

    response = client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": new.id})

    assert response.status_code == 503
    db_session.expire_all()
    assert db_session.get(type(flag), flag.id).status == ConflictStatus.OPEN
    assert get_document(db_session, old.id).status == DocumentStatus.COMPLETED
    assert get_document(db_session, old.id).is_current is True
    assert get_document(db_session, new.id).review_status == DocumentReviewStatus.PENDING


def test_unknown_mysql_commit_outcome_never_reactivates_pre_resolution_state(
    client,
    db_session,
    conflict,
    monkeypatch,
):
    flag, old, new = conflict
    new.is_current = False
    db_session.commit()
    calls: list[tuple[int, bool]] = []
    monkeypatch.setattr(
        vector_store_service,
        "update_document_vector_metadata",
        lambda document_id, **metadata: calls.append((document_id, metadata["is_current"])),
    )
    real_commit = db_session.commit
    commit_count = 0

    def commit_then_lose_ack():
        nonlocal commit_count
        commit_count += 1
        real_commit()
        if commit_count == 1:
            raise SQLAlchemyError("lost commit acknowledgement")

    db_session.commit = commit_then_lose_ack

    response = client.post(
        f"/api/v1/admin/conflicts/{flag.id}/resolve",
        json={"keep_document_id": new.id},
    )

    assert response.status_code == 503
    db_session.expire_all()
    assert db_session.get(type(flag), flag.id).status == ConflictStatus.RESOLVED
    assert get_document(db_session, old.id).is_current is False
    assert calls == [(old.id, False), (new.id, False)]


def test_winner_activation_failure_keeps_committed_decision_and_quarantine(
    client,
    db_session,
    conflict,
    monkeypatch,
):
    flag, old, new = conflict
    new.is_current = False
    db_session.commit()

    calls: list[tuple[int, bool]] = []
    activation_failed = False

    def fail_winner_activation(document_id, **metadata):
        nonlocal activation_failed
        is_current = metadata["is_current"]
        calls.append((document_id, is_current))
        if document_id == new.id and is_current and not activation_failed:
            activation_failed = True
            raise VectorStoreError("Qdrant unavailable")

    monkeypatch.setattr(vector_store_service, "update_document_vector_metadata", fail_winner_activation)

    response = client.post(f"/api/v1/admin/conflicts/{flag.id}/resolve", json={"keep_document_id": new.id})

    assert response.status_code == 503
    db_session.expire_all()
    assert db_session.get(type(flag), flag.id).status == ConflictStatus.RESOLVED
    assert get_document(db_session, old.id).is_current is False
    assert get_document(db_session, new.id).is_current is True
    assert calls == [
        (old.id, False),
        (new.id, False),
        (new.id, True),
    ]


def test_failed_winner_requarantine_never_reactivates_the_old_loser(
    client,
    db_session,
    conflict,
    monkeypatch,
):
    flag, old, new = conflict
    new.is_current = False
    db_session.commit()
    calls: list[tuple[int, bool]] = []

    def fail_winner_updates(document_id, **metadata):
        is_current = metadata["is_current"]
        calls.append((document_id, is_current))
        if document_id == new.id:
            raise VectorStoreError("Qdrant unavailable")

    monkeypatch.setattr(vector_store_service, "update_document_vector_metadata", fail_winner_updates)

    response = client.post(
        f"/api/v1/admin/conflicts/{flag.id}/resolve",
        json={"keep_document_id": new.id},
    )

    assert response.status_code == 503
    assert calls == [
        (old.id, False),
        (new.id, False),
        (new.id, False),
    ]


def test_winner_stays_quarantined_until_all_of_its_conflicts_are_resolved(
    client,
    db_session,
    admin,
    vector_syncs,
):
    first = create_document(db_session, DocumentCreate(title="Bảng giá A"))
    second = create_document(db_session, DocumentCreate(title="Bảng giá B"))
    third = create_document(db_session, DocumentCreate(title="Bảng giá C"))
    for document in (first, second, third):
        document.status = DocumentStatus.COMPLETED
        document.is_current = False
    db_session.commit()

    conflict_ab = create_conflict(db_session, first.id, second.id, "A/B")
    conflict_ac = create_conflict(db_session, first.id, third.id, "A/C")

    response = client.post(
        f"/api/v1/admin/conflicts/{conflict_ab.id}/resolve",
        json={"keep_document_id": first.id},
    )
    assert response.status_code == 200
    assert get_document(db_session, first.id).is_current is False

    response = client.post(
        f"/api/v1/admin/conflicts/{conflict_ac.id}/resolve",
        json={"keep_document_id": first.id},
    )
    assert response.status_code == 200
    assert get_document(db_session, first.id).is_current is True
    assert get_document(db_session, first.id).reviewed_by == admin.id

    winner_syncs = [call for call in vector_syncs if call["document_id"] == first.id]
    assert [call["is_current"] for call in winner_syncs] == [False, False, False, True]


def test_open_edge_is_auto_resolved_after_both_endpoints_are_blocked(client, db_session, admin):
    first = create_document(db_session, DocumentCreate(title="A"))
    second = create_document(db_session, DocumentCreate(title="B"))
    third = create_document(db_session, DocumentCreate(title="C"))
    fourth = create_document(db_session, DocumentCreate(title="D"))
    for document in (first, second, third, fourth):
        document.status = DocumentStatus.COMPLETED
    db_session.commit()

    conflict_ab = create_conflict(db_session, first.id, second.id, "A/B")
    conflict_cd = create_conflict(db_session, third.id, fourth.id, "C/D")
    stale_bd = create_conflict(db_session, second.id, fourth.id, "B/D")

    assert (
        client.post(
            f"/api/v1/admin/conflicts/{conflict_ab.id}/resolve",
            json={"keep_document_id": first.id},
        ).status_code
        == 200
    )
    db_session.refresh(stale_bd)
    assert stale_bd.status == ConflictStatus.OPEN

    assert (
        client.post(
            f"/api/v1/admin/conflicts/{conflict_cd.id}/resolve",
            json={"keep_document_id": third.id},
        ).status_code
        == 200
    )

    db_session.refresh(stale_bd)
    assert get_document(db_session, second.id).status == DocumentStatus.BLOCKED
    assert get_document(db_session, fourth.id).status == DocumentStatus.BLOCKED
    assert stale_bd.status == ConflictStatus.RESOLVED
    assert stale_bd.resolved_by == admin.id
    assert stale_bd.resolved_at is not None
