"""Working memory as assembled by the router — what actually reaches run_pipeline.

The prompt-side behaviour lives in tests/test_services/test_agent_pipeline_memory.py.
What matters here is the wiring: which rows are read, in what order, and which are
deliberately left out.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.user import User
from backend.services import agent_pipeline
from backend.services.agent_pipeline import PipelineResult


@pytest.fixture
def sale(db_session):
    user = User(username="sale_a", email="a@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(db_session, sale):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: sale
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def captured(monkeypatch):
    """Record the history handed to run_pipeline on each call, and answer with a canned reply."""
    calls: list[list[dict]] = []

    def fake_pipeline(query, project_id=None, db=None, history=None, **_kwargs):
        calls.append(list(history or []))
        return PipelineResult(
            draft_answer=f"Tra loi cho: {query}",
            citations=[],
            verifier_score=0.9,
            requires_hitl=False,
        )

    monkeypatch.setattr(agent_pipeline, "run_pipeline", fake_pipeline)
    return calls


def _session(client: TestClient) -> int:
    return client.post("/api/v1/sale/sessions", json={"title": "Khach A"}).json()["id"]


def _ask(client: TestClient, session_id: int, content: str) -> None:
    response = client.post(f"/api/v1/sale/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 201, response.text


def test_first_question_of_a_session_carries_no_history(client, captured):
    _ask(client, _session(client), "Gia can 2PN?")

    assert captured[0] == []


def test_the_question_being_asked_is_not_fed_back_as_its_own_context(client, captured):
    """Doc memory TRUOC khi luu cau hoi moi — nguoc lai model nhan chinh input cua no hai lan."""
    session_id = _session(client)
    _ask(client, session_id, "Gia can 2PN?")
    _ask(client, session_id, "Con 3PN thi sao?")

    assert [turn["content"] for turn in captured[1]] == ["Gia can 2PN?", "Tra loi cho: Gia can 2PN?"]


def test_history_arrives_oldest_first(client, captured):
    session_id = _session(client)
    _ask(client, session_id, "Cau 1")
    _ask(client, session_id, "Cau 2")
    _ask(client, session_id, "Cau 3")

    contents = [turn["content"] for turn in captured[2]]
    assert contents.index("Cau 1") < contents.index("Cau 2")


def test_speaker_is_recorded_on_every_turn(client, captured):
    session_id = _session(client)
    _ask(client, session_id, "Gia can 2PN?")
    _ask(client, session_id, "Con 3PN thi sao?")

    assert [turn["sender"] for turn in captured[1]] == ["sale", "agent"]


def test_edge_case_notices_are_not_replayed_as_context(client, captured, monkeypatch):
    """'Khong du thong tin' la trang thai UI, khong phai dieu tro ly noi ve du an."""
    session_id = _session(client)

    monkeypatch.setattr(
        agent_pipeline,
        "run_pipeline",
        lambda query, project_id=None, db=None, history=None, **_kwargs: PipelineResult(
            agent_pipeline.LOW_CONFIDENCE_MESSAGE_INTERNAL, [], 0.0, False
        ),
    )
    _ask(client, session_id, "Gia can 2PN?")

    def fake_pipeline(query, project_id=None, db=None, history=None, **_kwargs):
        captured.append(list(history or []))
        return PipelineResult("ok", [], 0.9, False)

    monkeypatch.setattr(agent_pipeline, "run_pipeline", fake_pipeline)
    _ask(client, session_id, "Con 3PN thi sao?")

    contents = [turn["content"] for turn in captured[-1]]
    assert contents == ["Gia can 2PN?"]
    assert agent_pipeline.LOW_CONFIDENCE_MESSAGE_INTERNAL not in contents


def test_sessions_do_not_share_memory(client, captured):
    """Moi phien la mot khach rieng — lich su khong duoc ro ri sang phien khac."""
    first = _session(client)
    _ask(client, first, "Gia can 2PN The Palma?")

    second = _session(client)
    _ask(client, second, "Con 3PN thi sao?")

    assert captured[-1] == []


def test_clearing_the_chat_also_clears_the_memory(client, captured):
    session_id = _session(client)
    _ask(client, session_id, "Gia can 2PN?")

    assert client.delete(f"/api/v1/sale/sessions/{session_id}/messages").status_code == 204

    _ask(client, session_id, "Con 3PN thi sao?")
    assert captured[-1] == []
