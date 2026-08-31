"""Feedback endpoints — who may rate and read which answers.

Message ids are sequential, so an endpoint that only checks "is someone logged in" lets
any account walk them across every other Sale's consultations. These tests are the guard
against that: the feedback loop is Sale-facing (CLAUDE.md 5.2e), and a CUSTOMER account
has no business reaching it at all.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import MessageSender, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.feedback import Feedback
from backend.models.message import Message
from backend.models.user import User


@pytest.fixture
def users(db_session):
    owner = User(username="owner", email="owner@example.com", hashed_password="x", role=UserRole.SALE)
    intruder = User(username="intruder", email="intruder@example.com", hashed_password="x", role=UserRole.SALE)
    customer = User(username="cust", email="cust@example.com", hashed_password="x", role=UserRole.CUSTOMER)
    admin = User(username="admin", email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
    db_session.add_all([owner, intruder, customer, admin])
    db_session.commit()
    for user in (owner, intruder, customer, admin):
        db_session.refresh(user)
    return {"owner": owner, "intruder": intruder, "customer": customer, "admin": admin}


@pytest.fixture
def as_user(db_session):
    def _login(user: User) -> TestClient:
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield _login
    app.dependency_overrides.clear()


def _answer_owned_by(db, owner: User) -> Message:
    """One AI answer inside a consultation session belonging to `owner`."""
    session = ChatSession(sale_id=owner.id, title="Khách A")
    db.add(session)
    db.commit()
    db.refresh(session)

    message = Message(session_id=session.id, sender=MessageSender.AGENT, content="Dự án có hồ bơi.")
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


class TestSubmitFeedback:
    def test_the_owner_can_rate_their_own_answer(self, as_user, users, db_session):
        message = _answer_owned_by(db_session, users["owner"])

        response = as_user(users["owner"]).post("/api/v1/feedback", json={"message_id": message.id, "type": "wrong"})

        assert response.status_code == 201, response.text
        assert db_session.query(Feedback).count() == 1

    def test_another_sale_cannot_rate_someone_elses_answer(self, as_user, users, db_session):
        """The core IDOR guard: ids are sequential, so guessing one must not be enough."""
        message = _answer_owned_by(db_session, users["owner"])

        response = as_user(users["intruder"]).post("/api/v1/feedback", json={"message_id": message.id, "type": "wrong"})

        assert response.status_code == 404
        assert db_session.query(Feedback).count() == 0

    def test_a_customer_account_is_rejected_outright(self, as_user, users, db_session):
        """Feedback is a Sale-facing loop; a customer must not reach it even for their own
        session, or the endpoint becomes a probe into internal consultation message ids."""
        message = _answer_owned_by(db_session, users["owner"])

        response = as_user(users["customer"]).post("/api/v1/feedback", json={"message_id": message.id, "type": "wrong"})

        assert response.status_code == 403
        assert db_session.query(Feedback).count() == 0

    def test_an_unknown_message_is_not_found(self, as_user, users):
        response = as_user(users["owner"]).post("/api/v1/feedback", json={"message_id": 999999, "type": "wrong"})

        assert response.status_code == 404


class TestReadFeedback:
    def test_another_sale_cannot_read_feedback_on_someone_elses_answer(self, as_user, users, db_session):
        message = _answer_owned_by(db_session, users["owner"])
        db_session.add(Feedback(message_id=message.id, type="wrong", user_id=users["owner"].id))
        db_session.commit()

        response = as_user(users["intruder"]).get(f"/api/v1/feedback/message/{message.id}")

        assert response.status_code == 404

    def test_the_owner_can_read_feedback_on_their_own_answer(self, as_user, users, db_session):
        message = _answer_owned_by(db_session, users["owner"])
        db_session.add(Feedback(message_id=message.id, type="wrong", user_id=users["owner"].id))
        db_session.commit()

        response = as_user(users["owner"]).get(f"/api/v1/feedback/message/{message.id}")

        assert response.status_code == 200, response.text
        assert len(response.json()) == 1

    def test_admin_may_read_any_answer_because_monitoring_quality_is_their_job(self, as_user, users, db_session):
        """Admin Tab 2 reviews answers across the whole team; `/top-failed` already exposes
        this team-wide, so confining Admin here would be inconsistent for no security gain."""
        message = _answer_owned_by(db_session, users["owner"])
        db_session.add(Feedback(message_id=message.id, type="wrong", user_id=users["owner"].id))
        db_session.commit()

        response = as_user(users["admin"]).get(f"/api/v1/feedback/message/{message.id}")

        assert response.status_code == 200, response.text
        assert len(response.json()) == 1

    def test_a_customer_account_is_rejected_outright(self, as_user, users, db_session):
        message = _answer_owned_by(db_session, users["owner"])

        response = as_user(users["customer"]).get(f"/api/v1/feedback/message/{message.id}")

        assert response.status_code == 403
