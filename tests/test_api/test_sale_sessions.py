"""Sale session flow — ownership isolation and the two delete endpoints the UI calls."""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import MessageSender, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.user import User
from backend.repositories.message import create_message
from backend.services import agent_pipeline, memory_service, reflection_memory, search_criteria
from backend.services.agent_pipeline import PipelineResult


@pytest.fixture
def sales(db_session):
    """Two distinct sales, so cross-account access can be exercised."""
    a = User(username="sale_a", email="a@example.com", hashed_password="x", role=UserRole.SALE)
    b = User(username="sale_b", email="b@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add_all([a, b])
    db_session.commit()
    db_session.refresh(a)
    db_session.refresh(b)
    return a, b


@pytest.fixture
def admin(db_session):
    """Admin cũng chat được — dùng để kiểm tra role không bị chặn khỏi luồng chat."""
    user = User(username="admin_a", email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def as_sale(db_session, sales):
    """Client factory that authenticates as a given user, bypassing JWT."""

    def _login(user: User) -> TestClient:
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield _login
    app.dependency_overrides.clear()


@pytest.fixture
def stub_pipeline(monkeypatch):
    """agent_pipeline.run_pipeline is still a TODO stub — these tests cover the
    session/message routes, not the RAG pipeline, so give it a canned answer."""
    monkeypatch.setattr(
        agent_pipeline,
        "run_pipeline",
        lambda query, project_id=None, db=None, history=None, **_kwargs: PipelineResult(
            draft_answer=f"Trả lời cho: {query}",
            citations=[],
            verifier_score=0.9,
            requires_hitl=False,
        ),
    )


def _create_session(client: TestClient, title: str = "Khách A") -> int:
    response = client.post("/api/v1/sale/sessions", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_delete_session_removes_it_from_the_list(as_sale, sales):
    client = as_sale(sales[0])
    session_id = _create_session(client)

    assert client.delete(f"/api/v1/sale/sessions/{session_id}").status_code == 204

    remaining = client.get("/api/v1/sale/sessions").json()
    assert [s["id"] for s in remaining] == []


def test_clear_messages_keeps_the_session(as_sale, sales, stub_pipeline):
    client = as_sale(sales[0])
    session_id = _create_session(client)
    client.post(f"/api/v1/sale/sessions/{session_id}/messages", json={"content": "Giá căn 2PN?"})

    assert client.get(f"/api/v1/sale/sessions/{session_id}/messages").json() != []

    assert client.delete(f"/api/v1/sale/sessions/{session_id}/messages").status_code == 204

    assert client.get(f"/api/v1/sale/sessions/{session_id}/messages").json() == []
    assert [s["id"] for s in client.get("/api/v1/sale/sessions").json()] == [session_id]


def test_admin_can_use_the_chat_flow(as_sale, admin, stub_pipeline):
    """Admin cũng tư vấn được: tạo phiên, hỏi, và nhận câu trả lời."""
    client = as_sale(admin)
    session_id = _create_session(client, title="Khách của Admin")

    reply = client.post(f"/api/v1/sale/sessions/{session_id}/messages", json={"content": "Giá căn 2PN?"})
    assert reply.status_code == 201, reply.text
    assert reply.json()["sender"] == "agent"

    assert [s["id"] for s in client.get("/api/v1/sale/sessions").json()] == [session_id]


def test_admin_cannot_read_a_sales_session(as_sale, sales, admin, stub_pipeline):
    """Mở chat cho admin không được phá cách ly: phiên của sale vẫn là riêng tư."""
    owner = sales[0]
    session_id = _create_session(as_sale(owner), title="Khách riêng của Sale")

    admin_client = as_sale(admin)
    assert admin_client.get(f"/api/v1/sale/sessions/{session_id}/messages").status_code == 404
    assert admin_client.delete(f"/api/v1/sale/sessions/{session_id}").status_code == 404
    assert admin_client.get("/api/v1/sale/sessions").json() == []


def test_a_sale_cannot_touch_another_sales_session(as_sale, sales, stub_pipeline):
    owner, intruder = sales
    owner_client = as_sale(owner)
    session_id = _create_session(owner_client, title="Khách riêng")

    other_client = as_sale(intruder)

    assert other_client.get(f"/api/v1/sale/sessions/{session_id}/messages").status_code == 404
    assert other_client.delete(f"/api/v1/sale/sessions/{session_id}").status_code == 404
    assert other_client.post(f"/api/v1/sale/sessions/{session_id}/messages", json={"content": "hi"}).status_code == 404

    assert [s["id"] for s in as_sale(owner).get("/api/v1/sale/sessions").json()] == [session_id]


def test_each_sale_session_is_one_customer_memory_boundary(as_sale, sales, monkeypatch):
    """Two customers of the same Sale share neither history, profile nor reflections."""
    client = as_sale(sales[0])
    customer_a = _create_session(client, title="Customer A")
    customer_b = _create_session(client, title="Customer B")

    loaded_keys: list[str] = []
    remembered_keys: list[str] = []
    pipeline_calls: list[dict] = []

    def _load(key: str):
        loaded_keys.append(key)
        return memory_service.UserProfile(topics=[key])

    def _remember(key: str, *_args, **_kwargs):
        remembered_keys.append(key)

    def _run(query, *, history=None, memory_profile="", session_id=None, reflection_scope=None, **_kwargs):
        pipeline_calls.append(
            {
                "query": query,
                "history": history,
                "memory_profile": memory_profile,
                "session_id": session_id,
                "reflection_scope": reflection_scope,
            }
        )
        return PipelineResult("ok", [], 0.9, False)

    monkeypatch.setattr(memory_service, "load_profile", _load)
    monkeypatch.setattr(memory_service, "remember", _remember)
    monkeypatch.setattr(agent_pipeline, "run_pipeline", _run)

    assert (
        client.post(f"/api/v1/sale/sessions/{customer_a}/messages", json={"content": "Ngân sách dưới 5 tỷ"}).status_code
        == 201
    )
    assert (
        client.post(f"/api/v1/sale/sessions/{customer_b}/messages", json={"content": "Tìm căn 3PN"}).status_code == 201
    )
    assert (
        client.post(
            f"/api/v1/sale/sessions/{customer_a}/messages", json={"content": "Ưu tiên căn còn trống"}
        ).status_code
        == 201
    )

    key_a = memory_service.sale_session_key(customer_a)
    key_b = memory_service.sale_session_key(customer_b)
    assert loaded_keys == [key_a, key_b, key_a]
    assert remembered_keys == [key_a, key_b, key_a]
    assert key_a != key_b

    assert pipeline_calls[0]["history"] == []
    assert pipeline_calls[1]["history"] == []
    assert [turn["content"] for turn in pipeline_calls[2]["history"]] == ["Ngân sách dưới 5 tỷ", "ok"]
    assert [call["reflection_scope"] for call in pipeline_calls] == [
        reflection_memory.sale_session_scope(customer_a),
        reflection_memory.sale_session_scope(customer_b),
        reflection_memory.sale_session_scope(customer_a),
    ]


def test_memory_question_backfills_only_that_sessions_human_turns(as_sale, sales, db_session, monkeypatch):
    client = as_sale(sales[0])
    session_id = _create_session(client, title="Existing customer")
    create_message(
        db_session,
        session_id,
        sender=MessageSender.SALE,
        content="Khách đang so sánh The Pavilion và The Sapphire, tài chính 3.5 - 4 tỷ",
    )
    create_message(db_session, session_id, sender=MessageSender.AGENT, content="Previous generated answer")

    profile = memory_service.UserProfile()
    backfilled: list[tuple[str, list[str]]] = []
    pipeline_profiles: list[memory_service.UserProfile] = []

    def _backfill(key, questions, *_args, **_kwargs):
        backfilled.append((key, questions))
        profile.projects = ["the-pavilion", "the-sapphire"]
        profile.budgets = ["3.5 - 4 tỷ"]

    def _run(_query, *, memory_profile_data=None, **_kwargs):
        pipeline_profiles.append(memory_profile_data)
        return PipelineResult("Memory answer", [], 1.0, False)

    monkeypatch.setattr(memory_service, "remember_many", _backfill)
    monkeypatch.setattr(memory_service, "load_profile", lambda _key: profile)
    monkeypatch.setattr(memory_service, "remember", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_pipeline, "run_pipeline", _run)

    response = client.post(
        f"/api/v1/sale/sessions/{session_id}/messages",
        json={"content": "Khách của tôi đang quan tâm đến phân khu nào?"},
    )

    assert response.status_code == 201
    assert backfilled == [
        (
            memory_service.sale_session_key(session_id),
            ["Khách đang so sánh The Pavilion và The Sapphire, tài chính 3.5 - 4 tỷ"],
        )
    ]
    assert pipeline_profiles[0].projects == ["the-pavilion", "the-sapphire"]


def test_clear_and_delete_forget_only_that_customer_memory(as_sale, sales, monkeypatch):
    client = as_sale(sales[0])
    session_id = _create_session(client)
    forgotten_profiles: list[str] = []
    forgotten_reflections: list[str | None] = []
    cleared_criteria: list[int] = []

    monkeypatch.setattr(memory_service, "forget", forgotten_profiles.append)
    monkeypatch.setattr(reflection_memory, "forget_all", forgotten_reflections.append)
    monkeypatch.setattr(search_criteria, "clear", cleared_criteria.append)

    assert client.delete(f"/api/v1/sale/sessions/{session_id}/messages").status_code == 204
    assert forgotten_profiles == [memory_service.sale_session_key(session_id)]
    assert forgotten_reflections == [reflection_memory.sale_session_scope(session_id)]
    assert cleared_criteria == [session_id]

    assert client.delete(f"/api/v1/sale/sessions/{session_id}").status_code == 204
    assert forgotten_profiles == [memory_service.sale_session_key(session_id)] * 2
    assert forgotten_reflections == [reflection_memory.sale_session_scope(session_id)] * 2
    assert cleared_criteria == [session_id, session_id]
