"""Short-term memory verified end-to-end: the real router, the real LangGraph pipeline,
the real prompt assembly — nothing monkeypatched except the three external services
(Qdrant, Gemini generate, Gemini verify).

tests/test_api/test_sale_chat_memory.py proves the router *wires* history correctly by
replacing run_pipeline outright, so it never actually exercises cache_check -> retrieve
-> generate -> verify with that history. This file closes that gap: it lets the real
graph run across two real turns and asserts the second turn's *prompt* — the thing
generate_text actually receives — contains the first turn's question and answer, in
Vietnamese, oldest-first, exactly as prompts._format_history renders it.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.user import User
from backend.services import agent_pipeline, verifier_service
from backend.services.verifier_service import VerifierResult


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
def wired_pipeline(monkeypatch):
    """Stub only the three services genuinely external to this process.

    retrieve: stands in for Qdrant — always returns one grounding chunk so `_generate`
    and `_verify` have context to work with.
    generate_json: stands in for the Gemini call. Records the exact prompt it was given
    and returns a canned answer that never trips risk_service (no price/commitment
    wording) and never asks for images, so the graph takes the plain verify -> risk_check
    -> END path every time.
    verifier_service.score_answer: stands in for the Gemini judge call, always passes,
    so every turn reaches risk_check/END rather than the low-confidence branch.

    Everything else — cache_check, the LangGraph wiring itself, prompts.build_prompt,
    prompts._format_history, risk_service.detect_commitment_risk — runs for real.
    """
    prompts_seen: list[str] = []

    def fake_retrieve(*_args, **_kwargs):
        return [
            {
                "document_id": 1,
                "title": "Bang gia The Zurich.pdf",
                "page": 1,
                "content": "Can 2PN gia 3.6 ty dong, can 3PN gia 5.2 ty dong.",
                "score": 0.9,
            }
        ]

    def fake_generate(prompt: str, schema, system_instruction: str | None = None):
        prompts_seen.append(prompt)
        return schema(text="Can 2PN gia 3.6 ty dong.")

    def fake_score(*_args, **_kwargs) -> VerifierResult:
        return VerifierResult(faithfulness=0.95, relevancy=0.95)

    monkeypatch.setattr(agent_pipeline, "retrieve", fake_retrieve)
    monkeypatch.setattr(agent_pipeline, "generate_json", fake_generate)
    monkeypatch.setattr(verifier_service, "score_answer", fake_score)

    return prompts_seen


def _session(client: TestClient) -> int:
    return client.post("/api/v1/sale/sessions", json={"title": "Khach A"}).json()["id"]


def _ask(client: TestClient, session_id: int, content: str) -> None:
    response = client.post(f"/api/v1/sale/sessions/{session_id}/messages", json={"content": content})
    assert response.status_code == 201, response.text


def test_second_turn_prompt_carries_the_first_turns_question_and_answer(client, wired_pipeline):
    """The real generate_text call on turn 2 must actually see turn 1, not just the DB."""
    session_id = _session(client)

    _ask(client, session_id, "Gia can 2PN?")
    _ask(client, session_id, "Con 3PN thi sao?")

    assert len(wired_pipeline) == 2
    first_prompt, second_prompt = wired_pipeline

    assert "LỊCH SỬ HỘI THOẠI" not in first_prompt

    assert "LỊCH SỬ HỘI THOẠI" in second_prompt
    assert "Sale: Gia can 2PN?" in second_prompt
    assert "Bạn: Can 2PN gia 3.6 ty dong." in second_prompt
    assert "CÂU HỎI CỦA SALE:\nCon 3PN thi sao?" in second_prompt
    assert second_prompt.index("Sale: Gia can 2PN?") < second_prompt.index("CÂU HỎI CỦA SALE:\nCon 3PN thi sao?")


def test_cache_is_bypassed_once_a_session_has_history(client, wired_pipeline, monkeypatch):
    """Real _cache_check node, real graph: turn 2 must not short-circuit through the cache."""
    calls = []
    monkeypatch.setattr(
        agent_pipeline.cache_service,
        "lookup_cache",
        lambda *a, **k: calls.append((a, k)) or None,
    )

    session_id = _session(client)
    _ask(client, session_id, "Gia can 2PN?")
    calls.clear()
    _ask(client, session_id, "Con 3PN thi sao?")

    assert calls == []


def test_a_fresh_session_for_the_same_sale_starts_with_no_history_in_the_prompt(client, wired_pipeline):
    """Two sessions are two different customers — history must not leak across them."""
    first = _session(client)
    _ask(client, first, "Gia can 2PN The Palma?")

    second = _session(client)
    _ask(client, second, "Con 3PN thi sao?")

    assert "LỊCH SỬ HỘI THOẠI" not in wired_pipeline[-1]
