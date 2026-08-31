"""run_pipeline's deterministic MessageEmotion mapping — drives AuremontAvatar.tsx.

Computed from the pipeline's own outcome (no extra LLM call), so these tests exercise the
real `run_pipeline` entry point with only the LangGraph invocation itself faked out —
everything below that (the emotion assignment at each return site) runs for real.
"""

from backend.core.enums import MessageEmotion
from backend.services import agent_pipeline


class _FakeGraph:
    def __init__(self, state: dict):
        self._state = state

    def invoke(self, _initial):
        return self._state


def test_successful_answer_is_happy(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline,
        "_get_graph",
        lambda: _FakeGraph({"draft_answer": "Căn 2PN giá 3.6 tỷ.", "citations": [], "verifier_score": 0.9}),
    )
    monkeypatch.setattr(agent_pipeline.cache_service, "store_cache", lambda **_kwargs: None)

    result = agent_pipeline.run_pipeline("Giá căn 2PN?")

    assert result.emotion == MessageEmotion.HAPPY


def test_notice_edge_case_is_regretful(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline,
        "_get_graph",
        lambda: _FakeGraph({"notice": agent_pipeline.EMPTY_STATE_MESSAGE_INTERNAL, "images": []}),
    )

    result = agent_pipeline.run_pipeline("Giá căn 2PN?")

    assert result.draft_answer == agent_pipeline.EMPTY_STATE_MESSAGE_INTERNAL
    assert result.emotion == MessageEmotion.REGRETFUL


def test_notice_carries_images_for_a_genuine_decline(monkeypatch):
    """Low-confidence/empty-state notices are a considered decline on the *text* only — the
    photos were still real and requested, so they ride along under the notice."""
    monkeypatch.setattr(
        agent_pipeline,
        "_get_graph",
        lambda: _FakeGraph(
            {
                "notice": agent_pipeline.LOW_CONFIDENCE_MESSAGE_PUBLIC,
                "images": [{"url": "https://cdn/p/x/anh.jpg", "project_id": "x", "project_name": "X"}],
            }
        ),
    )

    result = agent_pipeline.run_pipeline("Giá căn 2PN?")

    assert result.draft_answer == agent_pipeline.LOW_CONFIDENCE_MESSAGE_PUBLIC
    assert result.images == [{"url": "https://cdn/p/x/anh.jpg", "project_id": "x", "project_name": "X"}]


def test_notice_drops_images_for_a_system_failure(monkeypatch):
    """RETRIEVAL_ERROR_MESSAGE/GENERATION_ERROR_MESSAGE are a real system failure (Gemini
    down/rate-limited), not a considered decline — showing "temporarily unavailable" next
    to a leftover photo strip reads as a broken, half-working reply."""
    monkeypatch.setattr(
        agent_pipeline,
        "_get_graph",
        lambda: _FakeGraph(
            {
                "notice": agent_pipeline.GENERATION_ERROR_MESSAGE,
                "images": [{"url": "https://cdn/p/x/anh.jpg", "project_id": "x", "project_name": "X"}],
            }
        ),
    )

    result = agent_pipeline.run_pipeline("Giá căn 2PN?")

    assert result.draft_answer == agent_pipeline.GENERATION_ERROR_MESSAGE
    assert result.images == []


def test_empty_query_short_circuit_is_regretful():
    result = agent_pipeline.run_pipeline("   ")

    assert result.emotion == MessageEmotion.REGRETFUL


def test_pipeline_crash_is_regretful(monkeypatch):
    def _boom():
        raise RuntimeError("graph exploded")

    monkeypatch.setattr(agent_pipeline, "_get_graph", _boom)

    result = agent_pipeline.run_pipeline("Giá căn 2PN?")

    assert result.draft_answer == agent_pipeline.GENERATION_ERROR_MESSAGE
    assert result.emotion == MessageEmotion.REGRETFUL
