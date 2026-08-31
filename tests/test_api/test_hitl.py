"""HITL confirmation — authorization, idempotency and server-authoritative state.

This is the gate that stops an AI-generated price or commitment reaching a customer
unread, so the tests here are mostly negative: who may NOT confirm, and what a client
may NOT assert about confirmation state.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import MessageSender, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.hitl_log import HitlLog
from backend.models.message import Message
from backend.models.user import User


@pytest.fixture
def sales(db_session):
    owner = User(username="owner", email="owner@example.com", hashed_password="x", role=UserRole.SALE)
    intruder = User(username="intruder", email="intruder@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add_all([owner, intruder])
    db_session.commit()
    db_session.refresh(owner)
    db_session.refresh(intruder)
    return owner, intruder


@pytest.fixture
def as_user(db_session):
    def _login(user: User) -> TestClient:
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield _login
    app.dependency_overrides.clear()


def _risky_message(db, owner: User, requires_hitl: bool = True) -> Message:
    """A conversation owned by `owner` holding one answer that needs confirmation."""
    session = ChatSession(sale_id=owner.id, title="Khách A")
    db.add(session)
    db.commit()
    db.refresh(session)

    message = Message(
        session_id=session.id,
        sender=MessageSender.AGENT,
        content="Giá căn 2PN là 3,6 tỷ đồng.",
        requires_hitl=requires_hitl,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


class TestAuthorization:
    def test_the_owner_can_confirm(self, as_user, sales, db_session):
        owner, _ = sales
        message = _risky_message(db_session, owner)

        response = as_user(owner).post(
            f"/api/v1/hitl/{message.id}/confirm", json={"confirmed_content": message.content}
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "confirmed"

    def test_another_sale_cannot_confirm_someone_elses_message(self, as_user, sales, db_session):
        """The core IDOR guard: ids are sequential, so guessing one must not be enough."""
        owner, intruder = sales
        message = _risky_message(db_session, owner)

        response = as_user(intruder).post(f"/api/v1/hitl/{message.id}/confirm", json={"confirmed_content": "anything"})

        assert response.status_code == 404
        assert db_session.query(HitlLog).count() == 0

    def test_a_message_not_flagged_for_hitl_is_rejected(self, as_user, sales, db_session):
        owner, _ = sales
        message = _risky_message(db_session, owner, requires_hitl=False)

        response = as_user(owner).post(f"/api/v1/hitl/{message.id}/confirm", json={"confirmed_content": "x"})

        assert response.status_code == 400
        assert db_session.query(HitlLog).count() == 0

    def test_an_unknown_message_is_not_found(self, as_user, sales):
        owner, _ = sales
        response = as_user(owner).post("/api/v1/hitl/999999/confirm", json={"confirmed_content": "x"})
        assert response.status_code == 404


class TestIdempotency:
    def test_confirming_twice_records_one_decision(self, as_user, sales, db_session):
        """A double-click is one human decision; two audit rows would make the trail
        ambiguous about how many times the Sale actually reviewed the answer."""
        owner, _ = sales
        message = _risky_message(db_session, owner)
        client = as_user(owner)

        first = client.post(f"/api/v1/hitl/{message.id}/confirm", json={"confirmed_content": "A"})
        second = client.post(f"/api/v1/hitl/{message.id}/confirm", json={"confirmed_content": "B"})

        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert db_session.query(HitlLog).count() == 1


class TestServerAuthoritativeState:
    def test_an_unconfirmed_answer_is_reported_unconfirmed(self, as_user, sales, db_session):
        owner, _ = sales
        message = _risky_message(db_session, owner)

        listed = as_user(owner).get(f"/api/v1/sale/sessions/{message.session_id}/messages")

        assert listed.status_code == 200
        body = listed.json()[0]
        assert body["requires_hitl"] is True
        assert body["hitl_confirmed"] is False

    def test_confirmation_shows_up_on_reload(self, as_user, sales, db_session):
        """State survives a page refresh because it is derived from the audit trail
        rather than held in frontend memory."""
        owner, _ = sales
        message = _risky_message(db_session, owner)
        client = as_user(owner)

        client.post(f"/api/v1/hitl/{message.id}/confirm", json={"confirmed_content": message.content})
        listed = client.get(f"/api/v1/sale/sessions/{message.session_id}/messages")

        assert listed.json()[0]["hitl_confirmed"] is True

    def test_a_client_cannot_declare_its_own_answer_confirmed(self, as_user, sales, db_session):
        """hitl_confirmed is derived, never accepted as input."""
        owner, _ = sales
        session = ChatSession(sale_id=owner.id, title="Khách A")
        db_session.add(session)
        db_session.commit()
        db_session.refresh(session)

        response = as_user(owner).post(
            f"/api/v1/sale/sessions/{session.id}/messages",
            json={"content": "Giá căn 2PN?", "hitl_confirmed": True},
        )

        assert response.status_code == 201
        assert response.json()["hitl_confirmed"] is False


class TestDeletionWithConfirmations:
    """A conversation holding a confirmed answer must still be deletable.

    `hitl_logs.message_id` is a non-null FK with no cascade, so an incomplete delete order
    raises an integrity error. The visible symptom was worse than a plain failure: the
    frontend removed the row optimistically, so the conversation reappeared on reload.
    """

    def test_a_session_with_a_confirmed_answer_can_be_deleted(self, as_user, sales, db_session):
        owner, _ = sales
        message = _risky_message(db_session, owner)
        session_id = message.session_id
        client = as_user(owner)

        client.post(f"/api/v1/hitl/{message.id}/confirm", json={"confirmed_content": message.content})
        assert db_session.query(HitlLog).count() == 1

        deleted = client.delete(f"/api/v1/sale/sessions/{session_id}")

        assert deleted.status_code == 204, deleted.text
        assert client.get(f"/api/v1/sale/sessions/{session_id}/messages").status_code == 404
        assert db_session.query(HitlLog).count() == 0
        assert db_session.query(Message).filter(Message.session_id == session_id).count() == 0

    def test_the_session_is_gone_from_the_list_after_deleting(self, as_user, sales, db_session):
        """The reported bug: it disappeared, then came back on the next load."""
        owner, _ = sales
        message = _risky_message(db_session, owner)
        client = as_user(owner)

        session_id = message.session_id
        client.post(f"/api/v1/hitl/{message.id}/confirm", json={"confirmed_content": message.content})
        client.delete(f"/api/v1/sale/sessions/{session_id}")

        remaining = client.get("/api/v1/sale/sessions").json()
        assert [s["id"] for s in remaining] == []

    def test_clearing_history_also_clears_confirmations(self, as_user, sales, db_session):
        """ "Xóa chat" deletes messages too, so it hits the same foreign key."""
        owner, _ = sales
        message = _risky_message(db_session, owner)
        session_id = message.session_id
        client = as_user(owner)

        client.post(f"/api/v1/hitl/{message.id}/confirm", json={"confirmed_content": message.content})
        cleared = client.delete(f"/api/v1/sale/sessions/{session_id}/messages")

        assert cleared.status_code == 204, cleared.text
        assert client.get(f"/api/v1/sale/sessions/{session_id}/messages").json() == []
        assert db_session.query(HitlLog).count() == 0
