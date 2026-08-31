"""A generic "tư vấn giúp em" opener (zero retrieval hits, no inventory need, nothing
specific named) must reach Generate and have a real conversation — not the canned
"chưa có dữ liệu" wall, and not get zeroed out by Verify scoring an empty context.
"""

from backend.ai.intent import names_specific_document_topic
from backend.core.enums import DocumentVisibility
from backend.services import agent_pipeline


def test_names_specific_document_topic_true_for_keyword():
    assert names_specific_document_topic("cho tôi xin chính sách chiết khấu") is True


def test_names_specific_document_topic_false_for_generic_opener():
    assert names_specific_document_topic("bạn có thể tư vấn cho tôi không") is False


def test_retrieve_falls_through_to_generate_on_generic_opener_with_no_hits(monkeypatch):
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *_a, **_kw: [])

    result = agent_pipeline._retrieve(
        {"query": "bạn có thể tư vấn cho tôi không", "project_id": None, "clearance": DocumentVisibility.PUBLIC}
    )

    assert "notice" not in result
    assert result["retrieved_docs"] == []


def test_retrieve_still_shows_empty_state_for_specific_topic_with_no_hits(monkeypatch):
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *_a, **_kw: [])

    result = agent_pipeline._retrieve(
        {"query": "cho tôi xin bảng giá chi tiết", "project_id": None, "clearance": DocumentVisibility.PUBLIC}
    )

    assert result["notice"] == agent_pipeline.EMPTY_STATE_MESSAGE_PUBLIC


def test_route_after_generate_skips_verify_with_no_context():
    route = agent_pipeline._route_after_generate({"retrieved_docs": [], "inventory_units": []})

    assert route == "risk_check"


def test_route_after_generate_still_verifies_with_context():
    route = agent_pipeline._route_after_generate({"retrieved_docs": [{"document_id": 1}], "inventory_units": []})

    assert route == "verify"
