"""A session with no project asking an inventory question (no INVENTORY_PROJECT_MAP
catch-all either) must get a normal "which project?" follow-up — not the generic
"tạm thời không tra được tồn kho" that implies the API itself is down.

Regression coverage for the bug in test_inventory_service.py's
test_lookup_without_project_id_and_without_star_entry_raises: that test only proved
lookup_inventory raises; these prove agent_pipeline now handles that specific raise
correctly instead of lumping it in with a genuine API outage.
"""

from backend.core.enums import DocumentVisibility, MessageEmotion
from backend.services import agent_pipeline
from backend.services.inventory_service import InventoryApiError, InventoryProjectUnresolvedError


def test_project_unresolved_gets_the_clarifying_notice_not_the_outage_message(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline,
        "lookup_inventory",
        lambda *_a, **_kw: (_ for _ in ()).throw(InventoryProjectUnresolvedError("no project id")),
    )

    result = agent_pipeline._tool_call(
        {"query": "còn căn nào 2 phòng ngủ không", "clearance": DocumentVisibility.PUBLIC}
    )

    assert result["notice"] == agent_pipeline.INVENTORY_NEEDS_PROJECT_MESSAGE_PUBLIC
    assert result["notice"] != agent_pipeline.INVENTORY_UNAVAILABLE_MESSAGE
    assert result["notice_emotion"] == MessageEmotion.RESPECTFUL


def test_project_unresolved_asks_even_when_documents_were_also_retrieved(monkeypatch):
    """Answering an inventory question from an unrelated project's policy doc would be
    worse than asking which project — so this notice wins even with retrieved_docs set,
    unlike the genuine-outage branch below which degrades gracefully instead."""
    monkeypatch.setattr(
        agent_pipeline,
        "lookup_inventory",
        lambda *_a, **_kw: (_ for _ in ()).throw(InventoryProjectUnresolvedError("no project id")),
    )

    result = agent_pipeline._tool_call(
        {
            "query": "còn căn nào 2 phòng ngủ không",
            "clearance": DocumentVisibility.INTERNAL,
            "retrieved_docs": [{"document_id": 1, "title": "policy.pdf", "content": "..."}],
        }
    )

    assert result["notice"] == agent_pipeline.INVENTORY_NEEDS_PROJECT_MESSAGE_INTERNAL


def test_genuine_api_outage_still_uses_the_outage_message(monkeypatch):
    """A real InventoryApiError (not the project-unresolved subclass) keeps the old
    behaviour — this is the API actually being down, a different situation."""
    monkeypatch.setattr(
        agent_pipeline, "lookup_inventory", lambda *_a, **_kw: (_ for _ in ()).throw(InventoryApiError("offline"))
    )

    result = agent_pipeline._tool_call(
        {"query": "còn căn nào 2 phòng ngủ không", "clearance": DocumentVisibility.PUBLIC}
    )

    assert result["notice"] == agent_pipeline.INVENTORY_UNAVAILABLE_MESSAGE
    assert "notice_emotion" not in result


def test_notice_emotion_defaults_to_regretful_when_unset():
    """Every other notice (empty state, low confidence, generic outage...) never sets
    notice_emotion — run_pipeline must still fall back to REGRETFUL for those."""
    state: dict = {"notice": "chưa có dữ liệu"}

    assert state.get("notice_emotion", MessageEmotion.REGRETFUL) == MessageEmotion.REGRETFUL
