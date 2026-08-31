"""A customer-chat session carries no project by default (the picker was dropped from
session creation — see `_tool_call`'s docstring), so the only place a project the customer
named ever appears is inside the conversation itself.

Regression coverage for a live bug: a customer said "tư vấn cho tôi căn hộ dưới 5 tỷ", was
asked which project, answered "Ocean Park 1", was asked their purpose, answered "Đầu tư",
and was STILL asked for a budget from scratch a turn later — because nothing ever resolved
"Ocean Park 1" into a project id for `_tool_call` to use, so live inventory could never
actually run for this session. `_retrieve` now resolves a missing project id from the
(history-folded) conversation text, the same way `memory_service` already does for its own
purposes — see `answer_images_service.resolve_project_id`.

Second regression, found while fixing the first: every ingested chunk's `project_id`
payload field is NULL (an ingestion-pipeline gap — documents are never linked to a project
on upload). Threading the resolved id into the Qdrant `retrieve()` call as a hard filter
would therefore match zero chunks and silently turn a working unscoped search into an empty
one — see `test_resolution_never_scopes_the_qdrant_retrieve_call` below. The resolved id is
only for `_tool_call`, returned as `project_id` in the state dict; the Qdrant call keeps
using the session's own (unresolved) project id.
"""

from backend.core.enums import MessageSender
from backend.services import agent_pipeline
from backend.services.catalog_context_service import TowerContextResult


def _policy_hit() -> dict:
    return {"document_id": 1, "title": "policy.pdf", "content": "...", "score": 0.9}


def _stub_catalog_context(monkeypatch) -> None:
    """These tests use a bare `object()` as `db` — enough to satisfy `_retrieve`'s own
    "is a db configured at all" check, but not a real Session. `resolve_tower_context`
    (an unrelated concern to project resolution) would otherwise try real Session methods
    on it and raise; stub it out so only the project-resolution behaviour under test runs.
    """
    monkeypatch.setattr(
        agent_pipeline.catalog_context_service, "resolve_tower_context", lambda *_a, **_kw: TowerContextResult()
    )


def test_resolves_project_from_the_current_query_when_session_carries_none(monkeypatch):
    _stub_catalog_context(monkeypatch)

    def fake_resolve(_db, text):
        assert text == "Ocean Park 1"
        return "ocean-park-1"

    monkeypatch.setattr(agent_pipeline.answer_images_service, "resolve_project_id", fake_resolve)
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *_a, **_kw: [_policy_hit()])

    result = agent_pipeline._retrieve({"query": "Ocean Park 1", "project_id": None, "db": object()})

    assert result["project_id"] == "ocean-park-1"


def test_resolution_never_scopes_the_qdrant_retrieve_call(monkeypatch):
    """The regression found while fixing the bug above: passing the resolved id into
    `retrieve()` would filter Qdrant by a `project_id` payload field that is NULL on every
    ingested chunk today, turning a working unscoped search into a silent zero-hit one."""
    _stub_catalog_context(monkeypatch)
    seen_project_ids: list[str | None] = []

    def fake_resolve(_db, _text):
        return "ocean-park-1"

    def fake_retrieve(_query, _clearance, project_id, _top_k, **_kwargs):
        seen_project_ids.append(project_id)
        return [_policy_hit()]

    monkeypatch.setattr(agent_pipeline.answer_images_service, "resolve_project_id", fake_resolve)
    monkeypatch.setattr(agent_pipeline, "retrieve", fake_retrieve)

    agent_pipeline._retrieve({"query": "Ocean Park 1", "project_id": None, "db": object()})

    assert seen_project_ids == [None]


def test_resolves_project_named_a_turn_earlier_for_a_short_followup(monkeypatch):
    """The exact shape of the live bug: the project was named three turns back and the
    current turn ("Dưới 3 tỷ") is a short quick-reply tap that carries no topic of its own —
    `_retrieval_query`'s history fold is what surfaces "Ocean Park 1" again."""
    _stub_catalog_context(monkeypatch)

    def fake_resolve(_db, text):
        return "ocean-park-1" if "ocean park 1" in text.lower() else None

    monkeypatch.setattr(agent_pipeline.answer_images_service, "resolve_project_id", fake_resolve)
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *_a, **_kw: [_policy_hit()])

    history = [
        {"sender": MessageSender.CUSTOMER, "content": "có những dự án nào"},
        {"sender": MessageSender.AGENT, "content": "Ocean Park 1, 2, 3. Anh chị quan tâm dự án nào ạ?"},
        {"sender": MessageSender.CUSTOMER, "content": "Ocean Park 1"},
        {"sender": MessageSender.AGENT, "content": "Mua để ở hay đầu tư ạ?"},
        {"sender": MessageSender.CUSTOMER, "content": "Đầu tư"},
    ]

    result = agent_pipeline._retrieve({"query": "Dưới 3 tỷ", "project_id": None, "db": object(), "history": history})

    assert result["project_id"] == "ocean-park-1"


def test_the_sessions_own_project_id_wins_and_skips_resolution(monkeypatch):
    """A session that DOES carry a project (Sale flow, or a project-scoped customer page)
    must not have it second-guessed by whatever the conversation happens to mention."""
    _stub_catalog_context(monkeypatch)
    calls: list[str] = []

    def fake_resolve(_db, _text):
        calls.append("called")
        return "some-other-project"

    monkeypatch.setattr(agent_pipeline.answer_images_service, "resolve_project_id", fake_resolve)
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *_a, **_kw: [_policy_hit()])

    result = agent_pipeline._retrieve({"query": "Chính sách thanh toán?", "project_id": "ocean-park-3", "db": object()})

    assert result["project_id"] == "ocean-park-3"
    assert calls == []


def test_no_db_in_state_leaves_project_id_unresolved_instead_of_crashing(monkeypatch):
    """Defensive: `run_pipeline` always passes `db`, but `_retrieve` must degrade gracefully
    (same fail-open posture as memory_service) rather than raise if it's ever missing."""
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *_a, **_kw: [_policy_hit()])

    result = agent_pipeline._retrieve({"query": "Ocean Park 1", "project_id": None})

    assert result["project_id"] is None
