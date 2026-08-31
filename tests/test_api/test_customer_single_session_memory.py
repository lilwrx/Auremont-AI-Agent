import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user, get_optional_current_user
from backend.core.enums import MessageSender, SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.user import User
from backend.repositories.message import create_message, list_messages_for_session
from backend.services import agent_pipeline, memory_service, search_criteria
from backend.services.agent_pipeline import PipelineResult
from backend.services.memory_service import UserProfile


@pytest.fixture
def customer(db_session):
    user = User(
        username="single-session@example.com",
        email="single-session@example.com",
        hashed_password="x",
        role=UserRole.CUSTOMER,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def customer_client(db_session, customer):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: customer
    app.dependency_overrides[get_optional_current_user] = lambda: customer
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_customer_session_creation_is_idempotent(customer_client, db_session, customer):
    first = customer_client.post("/api/v1/customer/sessions", json={})
    second = customer_client.post("/api/v1/customer/sessions", json={})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert db_session.query(ChatSession).filter(ChatSession.customer_id == customer.id).count() == 1
    assert [row["id"] for row in customer_client.get("/api/v1/customer/sessions").json()] == [first.json()["id"]]


def test_customer_pipeline_receives_short_and_long_term_memory(customer_client, db_session, customer, monkeypatch):
    session_id = customer_client.post("/api/v1/customer/sessions", json={}).json()["id"]
    create_message(db_session, session_id, MessageSender.CUSTOMER, "Tôi muốn mua để ở")
    create_message(db_session, session_id, MessageSender.AGENT, "Anh chị dự kiến ngân sách bao nhiêu?")

    received = {}
    remembered = []
    monkeypatch.setattr(
        memory_service,
        "load_profile",
        lambda _key: UserProfile(unit_types=["2PN"], budgets=["4 tỷ"]),
    )
    monkeypatch.setattr(
        memory_service,
        "remember",
        lambda key, question, project_id=None, db=None: remembered.append((key, question)),
    )

    def fake_pipeline(query, **kwargs):
        received.update(kwargs)
        return PipelineResult("Câu trả lời", [], 1.0, False)

    monkeypatch.setattr(agent_pipeline, "run_pipeline", fake_pipeline)

    response = customer_client.post(
        f"/api/v1/customer/sessions/{session_id}/messages",
        json={"content": "Ngân sách tối đa 5 tỷ"},
    )

    assert response.status_code == 201
    assert received["session_id"] == session_id
    assert received["history"] == [
        {"sender": MessageSender.CUSTOMER, "content": "Tôi muốn mua để ở"},
        {"sender": MessageSender.AGENT, "content": "Anh chị dự kiến ngân sách bao nhiêu?"},
    ]
    assert "2PN" in received["memory_profile"]
    assert "4 tỷ" in received["memory_profile"]
    assert remembered == [(memory_service.customer_key(customer.id), "Ngân sách tối đa 5 tỷ")]


def test_login_claim_merges_anonymous_history_into_the_canonical_session(
    customer_client, db_session, customer, monkeypatch
):
    canonical_id = customer_client.post("/api/v1/customer/sessions", json={}).json()["id"]
    create_message(db_session, canonical_id, MessageSender.CUSTOMER, "Tôi quan tâm căn 2PN")

    anonymous = ChatSession(visitor_token="opaque-visitor-token")
    db_session.add(anonymous)
    db_session.commit()
    db_session.refresh(anonymous)
    create_message(db_session, anonymous.id, MessageSender.CUSTOMER, "Ngân sách của tôi tối đa 5 tỷ")

    remembered = []
    monkeypatch.setattr(
        memory_service,
        "remember",
        lambda key, question, project_id=None, db=None: remembered.append(question),
    )

    response = customer_client.post(
        "/api/v1/customer/sessions/claim-anonymous",
        json={"session_id": anonymous.id, "visitor_token": "opaque-visitor-token"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == canonical_id
    assert db_session.get(ChatSession, anonymous.id) is None
    assert [message.content for message in list_messages_for_session(db_session, canonical_id)] == [
        "Tôi quan tâm căn 2PN",
        "Ngân sách của tôi tối đa 5 tỷ",
    ]
    assert remembered == ["Tôi quan tâm căn 2PN", "Ngân sách của tôi tối đa 5 tỷ"]


def test_customer_clear_history_forgets_all_context_and_keeps_session(
    customer_client, db_session, customer, monkeypatch
):
    session_id = customer_client.post("/api/v1/customer/sessions", json={}).json()["id"]
    session = db_session.get(ChatSession, session_id)
    session.title = "Tư vấn căn 2PN"
    session.status = SessionStatus.WAITING_SALE
    db_session.commit()
    create_message(db_session, session_id, MessageSender.CUSTOMER, "Ngân sách tối đa 5 tỷ")
    create_message(db_session, session_id, MessageSender.AGENT, "Em đã ghi nhận")

    forgotten: list[str] = []
    cleared_criteria: list[int] = []
    monkeypatch.setattr(memory_service, "forget", lambda key: forgotten.append(key))
    monkeypatch.setattr(search_criteria, "clear", lambda sid: cleared_criteria.append(sid))

    response = customer_client.delete(f"/api/v1/customer/sessions/{session_id}/messages")

    assert response.status_code == 204
    assert list_messages_for_session(db_session, session_id) == []
    db_session.refresh(session)
    assert session.status == SessionStatus.BOT_HANDLING
    assert session.title is None
    assert forgotten == [memory_service.customer_key(customer.id)]
    assert cleared_criteria == [session_id]
    assert db_session.get(ChatSession, session_id) is not None
