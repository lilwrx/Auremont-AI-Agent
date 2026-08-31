"""Rule scoring and the LLM's strictly bounded contribution to it.

Pure functions only — no database, no Gemini. The wiring that decides WHEN this runs is
covered in tests/test_api/test_lead_scoring_wiring.py.
"""

import pytest

from backend.core.enums import LeadPurpose, LeadTier, LeadUrgency
from backend.services import lead_scoring_service as scoring
from backend.services import search_criteria

HOT, WARM = 65, 35


def _score(query: str, **kwargs) -> tuple[int, LeadTier, scoring.LeadSignals]:
    criteria = search_criteria.merge_criteria(search_criteria.SearchCriteria(), search_criteria.parse_criteria(query))
    signals = scoring.collect_signals(query, criteria, **kwargs)
    rule_score = scoring.score_rules(signals)
    return rule_score, scoring.classify(rule_score, signals, hot_threshold=HOT, warm_threshold=WARM), signals


def test_a_stated_budget_scores_but_a_price_question_does_not():
    """The highest-value test here: it locks in WHICH extractor reads the budget.

    `SearchCriteria` records any price a sentence mentions, so keying off it would score
    "căn này giá 3.6 tỷ có đắt không" — a question ABOUT a unit — as if the person had told
    us what they can afford. `memory_service`'s budget-context/price-question gate is what
    separates the two, and anyone "simplifying" this back to a price constraint turns every
    browser into a hot lead.
    """
    stated, _, stated_signals = _score("ngân sách của mình tầm 3.5 tỷ")
    asked, _, asked_signals = _score("căn 2PN giá 3.6 tỷ có đắt không")

    assert stated_signals.fired("stated_budget") is True
    assert asked_signals.fired("stated_budget") is False
    assert stated > asked


def test_budget_survives_being_written_beside_a_price_request():
    """ "Xin bảng giá, ngân sách tầm X" is how serious buyers actually write.

    The whole-string price-question gate suppresses the budget half, so the extractor runs
    per clause. Without this the most common qualified-buyer message scores as a browser.
    """
    _, tier, signals = _score("cho mình xin bảng giá căn 2PN, ngân sách tầm 3.5 tỷ")

    assert signals.fired("stated_budget") is True
    assert signals.fired("closing_intent") is True
    assert tier is LeadTier.WARM


def test_an_ambiguous_sentence_still_yields_no_budget():
    """Two figures in one clause compare units; picking the wrong one is worse than neither."""
    _, _, signals = _score("Ngân sách 3 tỷ thì căn 5 tỷ có hợp không?")

    assert signals.fired("stated_budget") is False


def test_a_decimal_budget_is_not_split_into_fragments():
    """Vietnamese money is written "3.5 tỷ" — splitting clauses on "." would destroy it."""
    _, _, signals = _score("ngân sách của mình tầm 3.5 tỷ")

    assert signals.fired("stated_budget") is True


def test_browsing_questions_stay_cold():
    for query in ("dự án ở đâu ạ", "chào shop", "có bao nhiêu tòa vậy"):
        score, tier, _ = _score(query)
        assert tier is LeadTier.COLD, f"{query!r} scored {score}"


@pytest.mark.parametrize(
    "query",
    (
        "Hôm nay tôi đặt cọc thì cần chuyển bao nhiêu?",
        "Gửi tôi bảng hàng còn trống mới nhất.",
        "Tôi muốn xem căn thực tế hoặc căn mẫu.",
        "Căn này hiện còn không?",
        "Có thể giữ căn cho tôi đến ngày mai không?",
        "Gửi tôi chính sách và tiến độ thanh toán cụ thể.",
        "Tính giúp tôi số tiền phải thanh toán từng đợt.",
        "Tính giúp tôi khoản vay và số tiền trả hằng tháng.",
        "Tôi cần chuẩn bị giấy tờ gì để ký hợp đồng?",
        "Khi nào có thể ký thỏa thuận đặt cọc?",
        "Tôi muốn gặp trực tiếp nhân viên tư vấn.",
        "Có thể sắp xếp lịch tham quan dự án cuối tuần này không?",
    ),
)
def test_high_intent_questions_are_warm_without_a_reachable_customer(query):
    score, tier, signals = _score(query)

    assert signals.fired("transaction_ready") or signals.fired("consideration_intent")
    assert score > 0
    assert tier is LeadTier.WARM


@pytest.mark.parametrize(
    "query",
    (
        "Giá bán hiện tại khoảng bao nhiêu?",
        "Chính sách thanh toán như thế nào?",
        "Dự án có căn mẫu không?",
        "Ngân hàng nào hỗ trợ cho vay?",
    ),
)
def test_general_research_questions_are_not_transaction_ready(query):
    _, _, signals = _score(query)

    assert signals.fired("transaction_ready") is False


def test_contact_details_alone_do_not_lift_a_price_list_request_to_hot():
    """Reachability is necessary for HOT, but it is not proof of transaction readiness."""
    query = "cho mình xin bảng giá căn 2PN, ngân sách tầm 3.5 tỷ"

    _, anonymous_tier, _ = _score(query)
    _, known_tier, _ = _score(query, is_registered=True, has_phone=True)

    assert anonymous_tier is LeadTier.WARM
    assert known_tier is LeadTier.WARM


def test_hot_requires_contact_action_and_a_qualifying_detail():
    query = "Tôi muốn đặt lịch xem căn A-1205 cuối tuần này"

    _, anonymous_tier, _ = _score(query)
    _, known_tier, signals = _score(query, is_registered=True, has_phone=True)

    assert signals.fired("transaction_ready") is True
    assert signals.fired("named_unit_code") is True
    assert anonymous_tier is LeadTier.WARM
    assert known_tier is LeadTier.HOT


def test_a_dated_viewing_with_contact_is_hot_but_an_undated_one_is_warm():
    _, dated_tier, dated_signals = _score("Tôi muốn xem căn thực tế cuối tuần này", is_registered=True, has_phone=True)
    _, undated_tier, _ = _score("Tôi muốn xem căn thực tế", is_registered=True, has_phone=True)

    assert dated_signals.fired("near_term_timeline") is True
    assert dated_tier is LeadTier.HOT
    assert undated_tier is LeadTier.WARM


def test_overlapping_intent_signals_only_contribute_once():
    score, tier, signals = _score("Cho mình gặp chuyên viên tư vấn")

    assert signals.fired("consideration_intent") is True
    assert signals.fired("wants_human") is True
    assert score == scoring._RULE_WEIGHTS["consideration_intent"]
    assert tier is LeadTier.WARM


def test_legacy_broad_transaction_flags_are_not_latched_into_the_new_rules():
    stored = {"transaction_ready": True, "closing_intent": True, "stated_budget": True}

    compatible = scoring.compatible_latched_flags(stored, "rules-2")

    assert compatible == {"stated_budget": True}


def test_utterance_signals_latch_so_a_later_thank_you_cannot_cool_a_lead():
    _, _, first = _score("em muốn đặt lịch xem nhà")
    assert first.fired("transaction_ready") is True

    later_score, _, later = _score("dạ vâng em cảm ơn ạ", latched=first.flags)

    assert later.fired("transaction_ready") is True
    assert later_score >= scoring._RULE_WEIGHTS["transaction_ready"]


def test_newly_latched_reports_only_the_signals_this_turn_added():
    _, _, first = _score("em muốn đặt lịch xem nhà")
    assert "transaction_ready" in first.newly_latched

    _, _, repeat = _score("em muốn đặt lịch xem nhà", latched=first.flags)
    assert repeat.newly_latched == ()


def _soft(**kwargs) -> scoring.LeadSoftSignals:
    return scoring.LeadSoftSignals(**kwargs)


def test_llm_alone_can_never_reach_warm():
    """The structural guarantee behind "hybrid, not pure-LLM".

    `SOFT_MAX` is below the WARM threshold, so a lead with zero hard signals cannot be
    promoted by the model no matter how certain it claims to be. If someone raises SOFT_MAX
    or lowers the WARM threshold past it, this fails — which is the point.
    """
    assert scoring.SOFT_MAX < WARM

    most_enthusiastic = _soft(
        urgency=LeadUrgency.IMMEDIATE, purpose=LeadPurpose.INVESTMENT, decision_ready=True, confidence=1.0
    )
    verdict = scoring.combine(0, scoring.LeadSignals(), most_enthusiastic, hot_threshold=HOT, warm_threshold=WARM)

    assert verdict.tier is LeadTier.COLD


def test_a_missing_llm_verdict_leaves_the_rule_score_standing():
    """Gemini being down must not empty the Sale's queue."""
    _, _, signals = _score("cho mình xin bảng giá căn 2PN, ngân sách tầm 3.5 tỷ")
    rule_score = scoring.score_rules(signals)

    verdict = scoring.combine(rule_score, signals, None, hot_threshold=HOT, warm_threshold=WARM)

    assert verdict.score == rule_score
    assert verdict.detection_method == "rule"
    assert verdict.soft_score is None


def test_enrich_returns_none_when_the_model_raises(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(scoring, "generate_json", _boom)

    assert scoring.enrich_with_llm(["em cần mua gấp trong tháng này"]) is None


@pytest.mark.parametrize("raw", ["", "URGENT", "rất gấp", None, 7])
def test_an_unreadable_urgency_degrades_downward(raw):
    """Never upward: a garbled verdict must not be why a Sale chases an invented HOT lead."""
    assert scoring.LeadSoftSignals(urgency=raw).urgency is LeadUrgency.EXPLORING


@pytest.mark.parametrize(("raw", "expected"), [(85, 0.85), (0.4, 0.4), ("nope", 0.0), (400, 1.0)])
def test_confidence_is_coerced_onto_the_zero_to_one_scale(raw, expected):
    assert scoring.LeadSoftSignals(confidence=raw).confidence == pytest.approx(expected)


def test_enrichment_is_skipped_outside_the_decision_band():
    """Below WARM the soft cap makes a tier change impossible; at HOT there is nothing to buy."""
    signals = scoring.LeadSignals()
    common = {"hot_threshold": HOT, "warm_threshold": WARM, "min_turns": 3, "turns_since_llm": 99}

    assert scoring.should_enrich(10, signals, **common) is False
    assert scoring.should_enrich(70, signals, **common) is False
    assert scoring.should_enrich(50, signals, **common) is True


def test_enrichment_waits_for_the_turn_gap_unless_a_new_signal_just_landed():
    quiet = scoring.LeadSignals()
    just_latched = scoring.LeadSignals(newly_latched=("closing_intent",))
    common = {"hot_threshold": HOT, "warm_threshold": WARM, "min_turns": 3}

    assert scoring.should_enrich(50, quiet, turns_since_llm=1, **common) is False
    assert scoring.should_enrich(50, just_latched, turns_since_llm=1, **common) is True
    assert scoring.should_enrich(50, quiet, turns_since_llm=None, **common) is True


def test_the_verdict_records_the_evidence_behind_it():
    """A tier with no evidence is an unauditable verdict — and unfixable when weights drift."""
    _, _, signals = _score("cho mình xin bảng giá căn 2PN, ngân sách tầm 3.5 tỷ")

    verdict = scoring.combine(scoring.score_rules(signals), signals, None, hot_threshold=HOT, warm_threshold=WARM)

    assert verdict.signals["flags"]["stated_budget"] is True
    assert verdict.signals["weights"]["closing_intent"] == 15
    assert verdict.signals["analysis_version"] == scoring.ANALYSIS_VERSION


def test_a_missing_soft_pass_carries_no_llm_reason_of_its_own():
    """`combine()` itself never invents a reason for a turn with no LLM pass.

    Whether a PREVIOUS turn's reason survives is repositories.lead.update_lead_score's job
    (it merges), not this pure function's — combine() only knows about this one turn.
    """
    _, _, signals = _score("cho mình xin bảng giá căn 2PN, ngân sách tầm 3.5 tỷ")

    verdict = scoring.combine(scoring.score_rules(signals), signals, None, hot_threshold=HOT, warm_threshold=WARM)

    assert "llm_reason" not in verdict.signals


def test_a_missing_phone_outranks_the_tier_in_the_next_action():
    """Telling a Sale to "call now" when there is no number to dial is worse than silence."""
    advice = scoring.suggest_next_action(LeadTier.HOT, has_phone=False, has_budget=True, wants_human=True, turn_count=5)

    assert "số điện thoại" in advice


def test_the_next_action_names_the_missing_piece_per_tier():
    hot = scoring.suggest_next_action(LeadTier.HOT, has_phone=True, has_budget=True, wants_human=True, turn_count=5)
    warm_no_budget = scoring.suggest_next_action(
        LeadTier.WARM, has_phone=True, has_budget=False, wants_human=False, turn_count=3
    )
    warm_with_budget = scoring.suggest_next_action(
        LeadTier.WARM, has_phone=True, has_budget=True, wants_human=False, turn_count=3
    )
    cold = scoring.suggest_next_action(LeadTier.COLD, has_phone=True, has_budget=False, wants_human=False, turn_count=1)

    assert "gọi ngay" in hot.lower()
    assert "ngân sách" in warm_no_budget
    assert "gửi" in warm_with_budget.lower()
    assert cold != warm_no_budget
