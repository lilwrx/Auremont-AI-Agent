"""Audit events emitted from the API routes, and what must never appear in them."""

import pytest
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.core.deps import get_current_user
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.user import User
from backend.services import agent_pipeline
from backend.services.agent_pipeline import PipelineResult


@pytest.fixture
def sale_user(db_session):
    user = User(username="sale_a", email="a@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def sale_client(db_session, sale_user):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: sale_user
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def stub_pipeline(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline,
        "run_pipeline",
        lambda query, project_id=None, db=None, history=None, **_kwargs: PipelineResult(
            draft_answer="Gia can 2PN la 3.6 ty dong.",
            citations=[{"document_id": 1, "title": "Bang gia", "page": 2}],
            verifier_score=0.91,
            requires_hitl=True,
            faithfulness=0.95,
            answer_relevancy=0.91,
        ),
    )


def _ask(client: TestClient, content: str = "Gia can 2PN?") -> int:
    session_id = client.post("/api/v1/sale/sessions", json={"title": "Khach A"}).json()["id"]
    response = client.post(f"/api/v1/sale/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 201, response.text
    return session_id


def test_sale_query_event_carries_the_quality_metrics(sale_client, stub_pipeline, capture_audit, sale_user):
    """These fields are what the Admin \"Danh gia AI\" dashboard is built from."""
    session_id = _ask(sale_client)

    record = next(r for r in capture_audit if r.event == "sale.query")
    assert record.session_id == session_id
    assert record.user_id == sale_user.id
    assert record.verifier_score == 0.91
    assert record.faithfulness == 0.95
    assert record.answer_relevancy == 0.91
    assert record.requires_hitl is True
    assert record.used_cache is False
    assert record.citation_count == 1
    assert isinstance(record.duration_ms, float)


def test_sale_query_records_the_question_text_by_default(sale_client, stub_pipeline, capture_audit):
    _ask(sale_client, "Gia can 2PN toa S1?")

    record = next(r for r in capture_audit if r.event == "sale.query")
    assert record.query == "Gia can 2PN toa S1?"
    assert record.query_len == len("Gia can 2PN toa S1?")


def test_query_text_can_be_switched_off_but_length_survives(sale_client, stub_pipeline, capture_audit, monkeypatch):
    """Turning off the text must not cost the volume signal the dashboard needs."""
    monkeypatch.setattr(settings, "log_query_text", False)

    _ask(sale_client, "Gia can 2PN toa S1?")

    record = next(r for r in capture_audit if r.event == "sale.query")
    assert record.query is None
    assert record.query_len == len("Gia can 2PN toa S1?")


def test_sale_query_never_logs_the_generated_answer(sale_client, stub_pipeline, capture_audit):
    """The answer is the thing a Sale reads to a customer; it stays out of logs."""
    _ask(sale_client)

    record = next(r for r in capture_audit if r.event == "sale.query")
    assert "3.6 ty" not in str(record.__dict__)


def test_hitl_confirm_is_audited_without_the_confirmed_content(sale_client, stub_pipeline, capture_audit):
    session_id = _ask(sale_client)
    messages = sale_client.get(f"/api/v1/sale/sessions/{session_id}/messages").json()
    agent_message = next(m for m in messages if m["requires_hitl"])

    secret_price_text = "Cam ket gia 3.6 ty dong cho khach hang."
    response = sale_client.post(
        f"/api/v1/hitl/{agent_message['id']}/confirm",
        json={"confirmed_content": secret_price_text},
    )
    assert response.status_code == 200, response.text

    record = next(r for r in capture_audit if r.event == "hitl.confirm")
    assert record.message_id == agent_message["id"]
    assert record.content_len == len(secret_price_text)
    assert record.edited is True
    assert secret_price_text not in str(record.__dict__)
