"""_generate's structured output for both audiences.

PUBLIC/customer gets text + quick_replies + listings + suggested_questions via
generate_json/ConsultAnswer; INTERNAL/Sale gets text + suggested_questions via
SaleAnswer and carries no quick replies or listings — see agent_pipeline._generate and
prompts.ConsultAnswer/SaleAnswer.
"""

from backend.ai.prompts import ConsultAnswer, PropertyListing, SaleAnswer
from backend.core.enums import DocumentVisibility
from backend.services import agent_pipeline


def test_public_clearance_uses_structured_output_and_keeps_quick_replies(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline,
        "generate_json",
        lambda *_a, **_kw: ConsultAnswer(text="Anh chị mua để ở hay đầu tư ạ?", quick_replies=["Để ở", "Đầu tư"]),
    )

    result = agent_pipeline._generate({"query": "tư vấn giúp em", "clearance": DocumentVisibility.PUBLIC})

    assert result["draft_answer"] == "Anh chị mua để ở hay đầu tư ạ?"
    assert result["quick_replies"] == ["Để ở", "Đầu tư"]


def test_public_clearance_fails_closed_when_unparseable(monkeypatch):
    monkeypatch.setattr(agent_pipeline, "generate_json", lambda *_a, **_kw: None)

    result = agent_pipeline._generate({"query": "tư vấn giúp em", "clearance": DocumentVisibility.PUBLIC})

    assert result == {"notice": agent_pipeline.GENERATION_ERROR_MESSAGE}


def test_internal_clearance_is_structured_but_has_no_quick_replies(monkeypatch):
    """SaleAnswer carries no quick_replies field at all — those exist to spare a customer
    typing on a phone, not a Sale at a keyboard (see prompts.SaleAnswer)."""
    monkeypatch.setattr(
        agent_pipeline,
        "generate_json",
        lambda *_a, **_kw: SaleAnswer(text="Giá căn 2PN là 3.6 tỷ."),
    )

    result = agent_pipeline._generate({"query": "giá căn 2PN?", "clearance": DocumentVisibility.INTERNAL})

    assert result["draft_answer"] == "Giá căn 2PN là 3.6 tỷ."
    assert result["quick_replies"] == []
    assert result["listings"] == []


def test_internal_clearance_fails_closed_when_unparseable(monkeypatch):
    """Same fail-closed posture as the PUBLIC path above, which INTERNAL did not have
    while it ran on plain generate_text."""
    monkeypatch.setattr(agent_pipeline, "generate_json", lambda *_a, **_kw: None)

    result = agent_pipeline._generate({"query": "giá căn 2PN?", "clearance": DocumentVisibility.INTERNAL})

    assert result == {"notice": agent_pipeline.GENERATION_ERROR_MESSAGE}


def test_public_clearance_carries_listings_through(monkeypatch):
    """Numeric details for a recommendation now live in `listings` (rendered as their own
    cards) rather than as bullet lines in `text` — see prompts.PropertyListing. No `db` on
    state here, so images/amenities/project_id can't resolve; the listing must still come
    through with those fields empty rather than being dropped."""
    monkeypatch.setattr(
        agent_pipeline,
        "generate_json",
        lambda *_a, **_kw: ConsultAnswer(
            text="Với ngân sách này, em gợi ý lựa chọn sau ạ:",
            listings=[
                PropertyListing(
                    project_name="The Sapphire 2", unit_type="2PN", area_range="55-64 m²", price_range="3,1-4,3 tỷ đồng"
                )
            ],
        ),
    )

    result = agent_pipeline._generate({"query": "tư vấn căn hộ dưới 5 tỷ", "clearance": DocumentVisibility.PUBLIC})

    assert result["listings"] == [
        {
            "project_name": "The Sapphire 2",
            "unit_type": "2PN",
            "area_range": "55-64 m²",
            "price_range": "3,1-4,3 tỷ đồng",
            "image_urls": [],
            "amenities": [],
            "project_id": None,
            "unit_code": "",
            "status": "",
            "tower": "",
        }
    ]


def test_suggested_questions_travel_out_of_generate_for_both_audiences(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline,
        "generate_json",
        lambda *_a, **_kw: SaleAnswer(text="- Căn 2PN từ 3,6 tỷ.", suggested_questions=["Diện tích bao nhiêu?"]),
    )
    internal = agent_pipeline._generate({"query": "giá căn 2PN?", "clearance": DocumentVisibility.INTERNAL})
    assert internal["suggested_questions"] == ["Diện tích bao nhiêu?"]

    monkeypatch.setattr(
        agent_pipeline,
        "generate_json",
        lambda *_a, **_kw: ConsultAnswer(text="Căn 2PN từ 3,6 tỷ ạ.", suggested_questions=["Tiện ích có gì ạ?"]),
    )
    public = agent_pipeline._generate({"query": "giá căn 2PN?", "clearance": DocumentVisibility.PUBLIC})
    assert public["suggested_questions"] == ["Tiện ích có gì ạ?"]
