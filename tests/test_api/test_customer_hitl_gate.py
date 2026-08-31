"""Customer self-service and Sale handoff boundaries.

Both logged-in and anonymous customers receive verified PUBLIC-tier price answers directly.
The conservative risk flag remains active on the Sale co-pilot, but it must not replace a
customer answer with a generic handoff.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user, get_optional_current_user
from backend.core.enums import SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.message import Message
from backend.models.user import User
from backend.repositories.message import create_message, list_messages_for_session
from backend.services import agent_pipeline
from backend.services.agent_pipeline import PipelineResult


@pytest.fixture
def customer(db_session):
    user = User(username="cust", email="cust@example.com", hashed_password="x", role=UserRole.CUSTOMER)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def as_customer(db_session):
    def _login(user: User) -> TestClient:
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_optional_current_user] = lambda: user
        return TestClient(app)

    yield _login
    app.dependency_overrides.clear()


@pytest.fixture
def anonymous_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_optional_current_user] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def _stub_pipeline(monkeypatch, *, requires_hitl: bool):
    monkeypatch.setattr(
        agent_pipeline,
        "run_pipeline",
        lambda query, project_id=None, db=None, clearance=None, history=None, **_kwargs: PipelineResult(
            draft_answer="Giá căn 2PN là 3,6 tỷ đồng.",
            citations=[],
            verifier_score=0.9,
            requires_hitl=requires_hitl,
        ),
    )


def _session_for(db, customer: User) -> ChatSession:
    session = ChatSession(customer_id=customer.id, status=SessionStatus.BOT_HANDLING)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _latest_agent_message(db, session_id: int) -> Message:
    return (
        db.query(Message)
        .filter(Message.session_id == session_id, Message.sender == "agent")
        .order_by(Message.id.desc())
        .first()
    )


def test_anonymous_visitor_can_clear_only_their_token_owned_history(anonymous_client, db_session):
    session = ChatSession(
        visitor_token="visitor-owner-token",
        title="Tra cứu dự án",
        status=SessionStatus.WAITING_SALE,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    create_message(db_session, session.id, "customer", "Dự án có tiện ích gì?")

    denied = anonymous_client.delete(
        f"/api/v1/customer/sessions/{session.id}/messages",
        headers={"X-Visitor-Token": "different-token"},
    )
    cleared = anonymous_client.delete(
        f"/api/v1/customer/sessions/{session.id}/messages",
        headers={"X-Visitor-Token": "visitor-owner-token"},
    )

    assert denied.status_code == 404
    assert cleared.status_code == 204
    assert list_messages_for_session(db_session, session.id) == []
    db_session.refresh(session)
    assert session.status == SessionStatus.BOT_HANDLING
    assert session.title is None


class TestLoggedInCustomer:
    def test_a_grounded_price_answer_reaches_the_customer_without_handoff(
        self, as_customer, customer, db_session, monkeypatch
    ):
        """A price detector flag must not swallow a self-service customer answer."""
        _stub_pipeline(monkeypatch, requires_hitl=True)
        session = _session_for(db_session, customer)

        response = as_customer(customer).post(
            f"/api/v1/customer/sessions/{session.id}/messages", json={"content": "Giá căn 2PN?"}
        )

        assert response.status_code == 201, response.text
        assert "3,6 tỷ" in response.json()["content"]
        assert response.json()["status"] == SessionStatus.BOT_HANDLING

        stored = _latest_agent_message(db_session, session.id)
        assert stored.requires_hitl is False
        assert "3,6 tỷ" in stored.content

    def test_a_price_answer_does_not_enter_the_live_queue(self, as_customer, customer, db_session, monkeypatch):
        _stub_pipeline(monkeypatch, requires_hitl=True)
        session = _session_for(db_session, customer)

        as_customer(customer).post(f"/api/v1/customer/sessions/{session.id}/messages", json={"content": "Giá căn 2PN?"})

        db_session.refresh(session)
        assert session.status == SessionStatus.BOT_HANDLING
        assert session.handoff_requested_at is None

    def test_detailed_price_question_reaches_the_pipeline(self, as_customer, customer, db_session, monkeypatch):
        _stub_pipeline(monkeypatch, requires_hitl=False)
        session = _session_for(db_session, customer)

        response = as_customer(customer).post(
            f"/api/v1/customer/sessions/{session.id}/messages",
            json={"content": "Cho mình xin bảng giá chi tiết"},
        )

        assert response.status_code == 201, response.text
        assert response.json()["status"] == SessionStatus.BOT_HANDLING
        assert "3,6 tỷ" in response.json()["content"]

    def test_a_safe_answer_still_reaches_the_customer_unchanged(self, as_customer, customer, db_session, monkeypatch):
        """The gate must not swallow ordinary answers — that would be a regression too."""
        _stub_pipeline(monkeypatch, requires_hitl=False)
        session = _session_for(db_session, customer)

        response = as_customer(customer).post(
            f"/api/v1/customer/sessions/{session.id}/messages", json={"content": "Dự án ở đâu?"}
        )

        assert response.status_code == 201, response.text
        assert response.json()["content"] == "Giá căn 2PN là 3,6 tỷ đồng."
        assert response.json()["status"] == SessionStatus.BOT_HANDLING


class TestAnonymousVisitor:
    def test_a_risky_answer_is_available_to_anonymous_self_service(self, anonymous_client, db_session, monkeypatch):
        _stub_pipeline(monkeypatch, requires_hitl=True)
        created = anonymous_client.post("/api/v1/customer/sessions/anonymous")
        assert created.status_code == 201, created.text
        session_id = created.json()["session_id"]
        token = created.json()["visitor_token"]

        response = anonymous_client.post(
            f"/api/v1/customer/sessions/{session_id}/messages",
            json={"content": "Giá căn 2PN?"},
            headers={"X-Visitor-Token": token},
        )

        assert response.status_code == 201, response.text
        assert response.json()["gate"] is None
        assert response.json()["status"] == SessionStatus.BOT_HANDLING
        assert "3,6 tỷ" in response.json()["content"]

        stored = _latest_agent_message(db_session, session_id)
        assert stored.requires_hitl is False

    @pytest.mark.parametrize(
        "question",
        [
            "Cho mình bảng giá chi tiết",
            "Cho mình xem mặt bằng chi tiết",
            "Tôi muốn đặt lịch xem căn",
            "Cho mình gặp Sale",
        ],
    )
    def test_anonymous_closing_questions_reach_self_service_pipeline(self, anonymous_client, monkeypatch, question):
        _stub_pipeline(monkeypatch, requires_hitl=False)
        created = anonymous_client.post("/api/v1/customer/sessions/anonymous")
        token = created.json()["visitor_token"]
        session_id = created.json()["session_id"]

        response = anonymous_client.post(
            f"/api/v1/customer/sessions/{session_id}/messages",
            json={"content": question},
            headers={"X-Visitor-Token": token},
        )

        assert response.status_code == 201, response.text
        assert response.json()["gate"] is None
