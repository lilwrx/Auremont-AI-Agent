"""The daily AI budget on the public chat.

The public chat is a marketing cost — no workspace is billed for a visitor's questions —
so this ceiling exists to bound that spend. It is counted per *identity per day* rather
than per session, because `customer_anonymous_turn_limit` resets the moment a visitor
opens a new conversation and therefore bounds nothing on its own.

These tests drive the HTTP surface and assert on what the AI actually did: the point is
not that a particular string came back, but that `run_pipeline` was never called once the
budget was gone.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.core.deps import get_current_user, get_optional_current_user
from backend.core.enums import SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.user import User
from backend.services import agent_pipeline
from backend.services.agent_pipeline import PipelineResult


@pytest.fixture
def calls(monkeypatch) -> list[str]:
    """Records every question that reached the pipeline, so a blocked turn is provable."""
    seen: list[str] = []

    def _run(query, project_id=None, db=None, clearance=None, history=None, **_kwargs):
        seen.append(query)
        return PipelineResult(
            draft_answer="Dạ, căn 2PN hiện còn trống ạ.",
            citations=[],
            verifier_score=0.9,
            requires_hitl=False,
        )

    monkeypatch.setattr(agent_pipeline, "run_pipeline", _run)
    return seen


@pytest.fixture
def customer(db_session):
    user = User(username="daily_cust", email="daily@example.com", hashed_password="x", role=UserRole.CUSTOMER)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def as_customer(db_session, customer):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: customer
    app.dependency_overrides[get_optional_current_user] = lambda: customer
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def anonymous_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_optional_current_user] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def _anonymous_session(db, token: str) -> ChatSession:
    session = ChatSession(visitor_token=token, status=SessionStatus.BOT_HANDLING)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _customer_session(db, customer: User) -> ChatSession:
    session = ChatSession(customer_id=customer.id, status=SessionStatus.BOT_HANDLING)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _ask(client: TestClient, session_id: int, text: str, token: str | None = None):
    headers = {"X-Visitor-Token": token} if token else {}
    return client.post(f"/api/v1/customer/sessions/{session_id}/messages", json={"content": text}, headers=headers)


def test_anonymous_visitor_is_cut_off_after_the_daily_allowance(anonymous_client, db_session, calls, monkeypatch):
    monkeypatch.setattr(settings, "customer_anonymous_daily_limit", 3)
    monkeypatch.setattr(settings, "customer_anonymous_turn_limit", 99)
    session = _anonymous_session(db_session, "visitor-daily")

    for index in range(3):
        assert _ask(anonymous_client, session.id, f"Câu hỏi {index}", "visitor-daily").status_code == 201

    blocked = _ask(anonymous_client, session.id, "Câu hỏi thứ tư", "visitor-daily")

    assert blocked.status_code == 201
    assert blocked.json()["gate"] == "daily_limit"
    assert len(calls) == 3, "the fourth question must never reach the model"


def test_clearing_the_transcript_does_not_refund_the_daily_allowance(anonymous_client, db_session, calls, monkeypatch):
    """Deleting the conversation must not buy more questions.

    `chat_sessions.visitor_token` is UNIQUE, so a visitor has exactly one anonymous
    session and cannot open a second to reset a per-session counter. The remaining way to
    look like a fresh start is to clear the transcript, which the product offers as a
    button — the daily budget has to survive it, or the ceiling is one click from useless.
    """
    monkeypatch.setattr(settings, "customer_anonymous_daily_limit", 3)
    monkeypatch.setattr(settings, "customer_anonymous_turn_limit", 99)
    session = _anonymous_session(db_session, "visitor-persist")

    for index in range(3):
        _ask(anonymous_client, session.id, f"Câu {index}", "visitor-persist")

    anonymous_client.delete(
        f"/api/v1/customer/sessions/{session.id}/messages",
        headers={"X-Visitor-Token": "visitor-persist"},
    )
    after_clearing = _ask(anonymous_client, session.id, "Câu hỏi sau khi xoá lịch sử", "visitor-persist")

    assert after_clearing.json()["gate"] == "daily_limit"
    assert len(calls) == 3


def test_a_different_visitor_has_their_own_budget(anonymous_client, db_session, calls, monkeypatch):
    monkeypatch.setattr(settings, "customer_anonymous_daily_limit", 3)
    monkeypatch.setattr(settings, "customer_anonymous_turn_limit", 99)
    spent = _anonymous_session(db_session, "visitor-a")
    for index in range(3):
        _ask(anonymous_client, spent.id, f"Câu {index}", "visitor-a")

    other = _anonymous_session(db_session, "visitor-b")
    response = _ask(anonymous_client, other.id, "Câu đầu tiên của người khác", "visitor-b")

    assert response.json()["gate"] is None
    assert len(calls) == 4


def test_registered_customers_get_the_larger_allowance(as_customer, db_session, customer, calls, monkeypatch):
    """The gap between the two numbers is the reward for signing up, so a registered
    customer must not be stopped at the anonymous ceiling."""
    monkeypatch.setattr(settings, "customer_anonymous_daily_limit", 3)
    monkeypatch.setattr(settings, "customer_registered_daily_limit", 10)
    session = _customer_session(db_session, customer)

    for index in range(10):
        response = _ask(as_customer, session.id, f"Câu hỏi {index}", None)
        assert response.json()["gate"] is None, f"blocked at question {index}"

    blocked = _ask(as_customer, session.id, "Câu thứ mười một", None)

    assert blocked.json()["gate"] == "daily_limit"
    assert len(calls) == 10


def test_the_blocked_turn_is_still_recorded_but_costs_no_model_call(anonymous_client, db_session, calls, monkeypatch):
    """A refused question is still the visitor's message and stays in their transcript —
    what it must not do is spend a Gemini call."""
    monkeypatch.setattr(settings, "customer_anonymous_daily_limit", 1)
    monkeypatch.setattr(settings, "customer_anonymous_turn_limit", 99)
    session = _anonymous_session(db_session, "visitor-record")

    _ask(anonymous_client, session.id, "Câu được trả lời", "visitor-record")
    _ask(anonymous_client, session.id, "Câu bị chặn", "visitor-record")

    messages = anonymous_client.get(
        f"/api/v1/customer/sessions/{session.id}/messages", headers={"X-Visitor-Token": "visitor-record"}
    ).json()
    customer_texts = [m["content"] for m in messages if m["sender"] == "customer"]

    assert "Câu bị chặn" in customer_texts
    assert len(calls) == 1
