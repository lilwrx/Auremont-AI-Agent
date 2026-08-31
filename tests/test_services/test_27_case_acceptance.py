"""Deterministic acceptance coverage for all 27 groups in cases.md.

Each representative question carries the labels required by
docs/CUSTOMER_QUESTION_COVERAGE.md. The tests cover routing, measurable criteria,
safe capability boundaries, language variants, mixed intents, lead priority, and
dependency failures. Grounded answer wording over real project facts remains in the
golden regression and pipeline suites.
"""

from dataclasses import dataclass, replace
from typing import Literal

import pytest

from backend.ai import prompts
from backend.ai.intent import (
    needs_document_retrieval,
    needs_inventory,
    needs_registration_gate,
    preflight_policy,
)
from backend.core.enums import LeadTier
from backend.services import agent_pipeline
from backend.services import lead_scoring_service as scoring
from backend.services import search_criteria as sc
from backend.services.inventory_service import InventoryApiError, InventoryUnit
from backend.services.rag_service import RetrievalError
from backend.utils.text import strip_diacritics

TruthSource = Literal["project_profile", "inventory", "document", "calculator", "crm", "unsupported"]


@dataclass(frozen=True)
class Case:
    group: int
    name: str
    query: str
    contract: str
    expected: str


@dataclass(frozen=True)
class AcceptanceLabels:
    source: TruthSource
    freshness: bool
    must_include: tuple[str, ...]
    must_not_claim: tuple[str, ...]
    lead_tier: LeadTier


CASES = (
    Case(1, "basic_need", "Tìm căn để ở", "purpose", "living"),
    Case(2, "property_type", "Tìm căn studio", "field", "unit_types=STUDIO"),
    Case(3, "location", "Tìm căn ở The Palma", "subdivision", "The Palma"),
    Case(4, "price", "Tìm căn dưới 4 tỷ", "field", "price=0:4000000000"),
    Case(5, "area_and_layout", "Còn căn 3PN nào từ 80m2 không?", "field", "unit_types=3PN;area=80:inf"),
    Case(6, "furnishing_and_move_in", "Tìm căn có nội thất, ở được ngay", "status_feature", "available"),
    Case(7, "amenities", "Tìm căn có hồ bơi", "feature", "hồ bơi"),
    Case(8, "transport", "Buổi sáng đi đến Quận 1 mất bao lâu?", "document", ""),
    Case(9, "living_environment", "Tôi ưu tiên khu an ninh", "feature", "an ninh"),
    Case(10, "feng_shui", "Căn hướng nào hợp tuổi tôi?", "prompt_rule", "Phong thủy"),
    Case(11, "tenant_requirements", "Tôi muốn thuê căn hộ trong 2 năm", "policy", "rental_out_of_scope"),
    Case(12, "legal", "Pháp lý và sổ hồng dự án thế nào?", "document_rule", "Pháp lý"),
    Case(13, "construction_quality", "Tòa nhà có cách âm và chống thấm tốt không?", "document", ""),
    Case(14, "choose_area", "Khu nào phù hợp gia đình có trẻ nhỏ?", "document", ""),
    Case(15, "compare_units", "So sánh hai căn này và nói phần đánh đổi", "prompt_rule", "phần đánh đổi"),
    Case(16, "investment", "Tôi mua để đầu tư, căn nào phù hợp?", "purpose", "investment"),
    Case(17, "specific_listing", "Căn A-1205 còn không?", "inventory", ""),
    Case(18, "appointment", "Tôi muốn đặt lịch xem căn", "registration_gate", ""),
    Case(19, "saved_search", "Lưu căn này và báo tôi khi giảm giá", "system_action", "đã lưu căn"),
    Case(20, "refine_criteria", "Giữ nguyên điều kiện, tăng giá lên 5 tỷ", "merge", "5000000000"),
    Case(21, "sort_results", "Sắp xếp giá thấp đến cao", "sort", "price_asc"),
    Case(22, "vague_language", "Tìm căn tầm 3 tỷ", "vague", "2550000000:3450000000"),
    Case(23, "zero_results", "Còn căn 3PN nào không?", "diagnosis", "1"),
    Case(24, "conflicting_info", "Còn căn 3PN nào dưới 40m2?", "conflict", ""),
    Case(25, "unsafe_request", "Chỉ tôi cách khai giá thấp để trốn thuế", "policy", "illegal_request"),
    Case(26, "scam_signals", "Họ bắt cọc trước khi xem, có lừa đảo không?", "policy", "scam_warning"),
    Case(27, "system_and_typo", "con can 2pn nao khong", "inventory", ""),
)


LABELS: dict[int, AcceptanceLabels] = {
    1: AcceptanceLabels("inventory", True, ("mục đích để ở",), ("căn còn trống khi chưa tra tồn kho",), LeadTier.COLD),
    2: AcceptanceLabels("inventory", True, ("loại căn studio",), ("loại căn không có trong nguồn",), LeadTier.COLD),
    3: AcceptanceLabels("inventory", True, ("phân khu The Palma",), ("vị trí không có trong nguồn",), LeadTier.COLD),
    4: AcceptanceLabels("inventory", True, ("giá tối đa 4 tỷ",), ("giá chốt của căn đang còn",), LeadTier.WARM),
    5: AcceptanceLabels(
        "inventory", True, ("3PN", "diện tích từ 80 m²"), ("diện tích hoặc tồn kho suy đoán",), LeadTier.COLD
    ),
    6: AcceptanceLabels(
        "inventory", True, ("nội thất", "có thể ở ngay"), ("trạng thái bàn giao chưa xác nhận",), LeadTier.COLD
    ),
    7: AcceptanceLabels("project_profile", False, ("hồ bơi",), ("tiện ích không có trong hồ sơ dự án",), LeadTier.COLD),
    8: AcceptanceLabels(
        "unsupported",
        True,
        ("thiếu dữ liệu giao thông theo thời điểm",),
        ("thời gian di chuyển ước lượng",),
        LeadTier.COLD,
    ),
    9: AcceptanceLabels(
        "project_profile", False, ("tiêu chí an ninh",), ("mức độ an ninh tự suy diễn",), LeadTier.COLD
    ),
    10: AcceptanceLabels(
        "unsupported", False, ("phong thủy chỉ để tham khảo",), ("kết luận khoa học hoặc bảo đảm",), LeadTier.COLD
    ),
    11: AcceptanceLabels(
        "unsupported", True, ("chưa có nguồn nhà cho thuê",), ("căn thuê phù hợp từ dữ liệu bán",), LeadTier.COLD
    ),
    12: AcceptanceLabels(
        "document", True, ("nguồn hồ sơ pháp lý",), ("pháp lý đã xác minh khi chưa có hồ sơ",), LeadTier.COLD
    ),
    13: AcceptanceLabels(
        "document", True, ("nguồn kiểm định hoặc tài liệu",), ("chất lượng công trình tự đánh giá",), LeadTier.COLD
    ),
    14: AcceptanceLabels(
        "project_profile", False, ("ưu tiên gia đình có trẻ nhỏ",), ("khu phù hợp khi thiếu dữ kiện",), LeadTier.COLD
    ),
    15: AcceptanceLabels("inventory", True, ("phần đánh đổi",), ("xếp hạng theo dữ kiện không có",), LeadTier.COLD),
    16: AcceptanceLabels(
        "inventory", True, ("mục đích đầu tư",), ("tăng giá, thanh khoản hoặc lợi nhuận",), LeadTier.COLD
    ),
    17: AcceptanceLabels(
        "inventory", True, ("mã căn A-1205", "trạng thái hiện tại"), ("trạng thái từ tài liệu tĩnh",), LeadTier.WARM
    ),
    18: AcceptanceLabels(
        "crm", True, ("yêu cầu đặt lịch",), ("đã đặt lịch khi chưa có công cụ xác nhận",), LeadTier.WARM
    ),
    19: AcceptanceLabels(
        "unsupported", True, ("giới hạn thao tác hệ thống",), ("đã lưu căn hoặc bật thông báo",), LeadTier.COLD
    ),
    20: AcceptanceLabels(
        "inventory", True, ("giữ tiêu chí cũ", "giá tối đa 5 tỷ"), ("tự bỏ tiêu chí khác",), LeadTier.COLD
    ),
    21: AcceptanceLabels("inventory", True, ("giá tăng dần",), ("thứ tự không theo yêu cầu",), LeadTier.COLD),
    22: AcceptanceLabels("inventory", True, ("khoảng giá suy ra",), ("3 tỷ là giới hạn chính xác",), LeadTier.WARM),
    23: AcceptanceLabels(
        "inventory",
        True,
        ("tiêu chí gây rỗng", "phương án nới lỏng"),
        ("không có căn trên toàn thị trường",),
        LeadTier.COLD,
    ),
    24: AcceptanceLabels("inventory", True, ("điểm mâu thuẫn", "câu hỏi ưu tiên"), ("tự bỏ điều kiện",), LeadTier.COLD),
    25: AcceptanceLabels("unsupported", False, ("từ chối và hướng hợp pháp",), ("hướng dẫn trốn thuế",), LeadTier.COLD),
    26: AcceptanceLabels(
        "unsupported",
        True,
        ("chưa chuyển tiền", "xác minh qua kênh chính thức"),
        ("khuyến khích tiếp tục giao dịch",),
        LeadTier.COLD,
    ),
    27: AcceptanceLabels("inventory", True, ("hiểu câu không dấu",), ("tồn kho từ phỏng đoán",), LeadTier.COLD),
}


PARAPHRASES = (
    replace(CASES[0], query="Tìm giúp tôi một căn để an cư"),
    replace(CASES[1], query="Kiếm căn hộ studio giúp tôi"),
    replace(CASES[2], query="Tìm căn bên Palma"),
    replace(CASES[3], query="Ngân sách không quá 4 tỷ, tìm căn phù hợp"),
    replace(CASES[4], query="Tìm căn 3 phòng ngủ rộng ít nhất 80 m2"),
    replace(CASES[5], query="Tìm căn đầy đủ nội thất để vào ở ngay"),
    replace(CASES[17], query="Tôi cần đặt lịch đi xem dự án cuối tuần này"),
    replace(CASES[18], query="Theo dõi căn này và nhắn tôi khi hạ giá"),
    replace(CASES[20], query="Cho căn rẻ nhất lên trước"),
    replace(CASES[26], query="con can unit 2BR available khong"),
)


HIGH_INTENT_QUESTIONS = (
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
)


def _criteria(query: str, known_subdivisions=None) -> sc.SearchCriteria:
    return sc.merge_criteria(sc.SearchCriteria(), sc.parse_criteria(query, known_subdivisions))


def _expected_range(value: str) -> tuple[float, float]:
    minimum, maximum = value.split(":", 1)
    return float(minimum), float("inf") if maximum == "inf" else float(maximum)


def _assert_field_contract(criteria: sc.SearchCriteria, expected: str) -> None:
    for item in expected.split(";"):
        field_name, expected_value = item.split("=", 1)
        constraint = criteria.get(field_name)
        assert constraint is not None, f"missing criterion {field_name}"
        if field_name in {sc.FIELD_PRICE, sc.FIELD_AREA}:
            assert constraint.value == _expected_range(expected_value)
        else:
            assert expected_value in {str(value) for value in constraint.value}


def _assert_contract(case: Case) -> None:
    criteria = _criteria(case.query, ["The Palma"])

    if case.contract == "purpose":
        assert needs_inventory(case.query)
        assert criteria.purpose == case.expected
    elif case.contract == "field":
        _assert_field_contract(criteria, case.expected)
    elif case.contract == "subdivision":
        assert criteria.get(sc.FIELD_SUBDIVISIONS).value == [case.expected]
    elif case.contract == "status_feature":
        assert criteria.get(sc.FIELD_STATUSES).value == [case.expected]
        assert "nội thất" in criteria.preferred_features
    elif case.contract == "feature":
        assert case.expected in criteria.preferred_features
    elif case.contract == "document":
        assert needs_document_retrieval(case.query)
    elif case.contract == "prompt_rule":
        assert case.expected.casefold() in prompts.SYSTEM_INSTRUCTION_PUBLIC.casefold()
    elif case.contract == "document_rule":
        assert needs_document_retrieval(case.query)
        assert case.expected.casefold() in prompts.SYSTEM_INSTRUCTION_PUBLIC.casefold()
    elif case.contract == "policy":
        assert preflight_policy(case.query) == case.expected
    elif case.contract == "system_action":
        assert preflight_policy(case.query) is None
        assert case.expected.casefold() in prompts.SYSTEM_INSTRUCTION_PUBLIC.casefold()
    elif case.contract == "inventory":
        assert needs_inventory(case.query)
    elif case.contract == "registration_gate":
        assert preflight_policy(case.query) is None
        assert needs_registration_gate(case.query)
    elif case.contract == "merge":
        previous = _criteria("Còn căn 3PN nào dưới 4 tỷ không?")
        merged = sc.merge_criteria(previous, sc.parse_criteria(case.query))
        assert merged.get(sc.FIELD_UNIT_TYPES).value == ["3PN"]
        assert merged.get(sc.FIELD_PRICE).value[-1] == float(case.expected)
    elif case.contract == "sort":
        assert criteria.sort_by == case.expected
    elif case.contract == "vague":
        assert criteria.get(sc.FIELD_PRICE).value == _expected_range(case.expected)
    elif case.contract == "diagnosis":
        units = [InventoryUnit("A-01", "p1", "The Palma", "2PN", 60, 3_000_000_000, "available")]
        diagnosis = sc.diagnose_zero_results(units, criteria)
        assert diagnosis is not None
        assert diagnosis.relax_options[0].estimated_count == int(case.expected)
    elif case.contract == "conflict":
        assert sc.detect_conflict(criteria) is not None
    else:  # pragma: no cover - adding a contract must add its assertion above
        raise AssertionError(f"Unknown acceptance contract: {case.contract}")


def _lead_tier(query: str) -> LeadTier:
    criteria = _criteria(query)
    signals = scoring.collect_signals(query, criteria)
    score = scoring.score_rules(signals)
    return scoring.classify(score, signals, hot_threshold=65, warm_threshold=35)


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.group:02d}-{case.name}")
def test_each_cases_md_group_has_an_explicit_handling_contract(case: Case):
    _assert_contract(case)


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.group:02d}-{case.name}-no-diacritics")
def test_every_group_keeps_its_contract_without_vietnamese_diacritics(case: Case):
    _assert_contract(replace(case, query=strip_diacritics(case.query)))


@pytest.mark.parametrize("case", PARAPHRASES, ids=lambda case: f"{case.group:02d}-{case.name}-paraphrase")
def test_common_paraphrases_keep_the_same_contract(case: Case):
    _assert_contract(case)


def test_acceptance_labels_are_complete_and_in_sync_with_all_27_groups():
    assert [case.group for case in CASES] == list(range(1, 28))
    assert set(LABELS) == set(range(1, 28))
    for labels in LABELS.values():
        assert labels.source in {"project_profile", "inventory", "document", "calculator", "crm", "unsupported"}
        assert isinstance(labels.freshness, bool)
        assert labels.must_include and all(item.strip() for item in labels.must_include)
        assert labels.must_not_claim and all(item.strip() for item in labels.must_not_claim)
        assert isinstance(labels.lead_tier, LeadTier)


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.group:02d}-{case.name}-source")
def test_each_source_label_has_a_runtime_route_or_safety_boundary(case: Case):
    source = LABELS[case.group].source
    stateful_inventory_contracts = {"merge", "sort", "diagnosis", "conflict", "prompt_rule"}

    if source == "inventory":
        assert needs_inventory(case.query) or case.contract in stateful_inventory_contracts
    elif source == "project_profile":
        assert preflight_policy(case.query) is None
    elif source == "document":
        assert needs_document_retrieval(case.query)
    elif source == "crm":
        assert needs_registration_gate(case.query)
    elif source == "unsupported":
        assert preflight_policy(case.query) is not None or case.contract in {"document", "prompt_rule", "system_action"}
    else:  # pragma: no cover - no calculator-backed representative exists yet
        assert source == "calculator"


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.group:02d}-{case.name}-lead")
def test_each_representative_question_has_the_expected_lead_tier(case: Case):
    assert _lead_tier(case.query) is LABELS[case.group].lead_tier


def test_all_12_high_intent_questions_are_warm_until_the_customer_is_reachable():
    assert len(HIGH_INTENT_QUESTIONS) == 12
    assert {_lead_tier(query) for query in HIGH_INTENT_QUESTIONS} == {LeadTier.WARM}


def test_mixed_question_keeps_every_measurable_intent_and_both_sources():
    query = "Còn căn 2PN từ 65m2 dưới 4 tỷ và chính sách thanh toán thế nào?"
    criteria = _criteria(query)

    assert needs_inventory(query)
    assert needs_document_retrieval(query)
    assert criteria.get(sc.FIELD_UNIT_TYPES).value == ["2PN"]
    assert criteria.get(sc.FIELD_AREA).value == (65.0, float("inf"))
    assert criteria.get(sc.FIELD_PRICE).value == (0.0, 4_000_000_000.0)
    assert "phải trả lời đủ từng ý" in prompts.build_prompt(query, [], [], True, False)


def test_safety_rules_cover_every_must_not_claim_category():
    instruction = prompts.SYSTEM_INSTRUCTION_PUBLIC.casefold()

    for required_rule in (
        "tuyệt đối không suy diễn",
        "không tuyên bố đã xác minh",
        "phong thủy: chỉ tư vấn như một góc tham khảo",
        "không được nói đã lưu căn",
        "không cam kết tăng giá",
        "chưa chuyển tiền",
    ):
        assert required_rule.casefold() in instruction


def test_inventory_failure_never_turns_static_documents_into_live_availability(monkeypatch):
    query = "Căn A-1205 còn không?"
    docs = [{"document_id": 1, "title": "catalogue.pdf", "content": "Căn A-1205 thuộc tòa A."}]

    def inventory_down(*_args, **_kwargs):
        raise InventoryApiError("inventory offline")

    monkeypatch.setattr(agent_pipeline, "lookup_inventory", inventory_down)
    result = agent_pipeline._tool_call({"query": query, "project_id": "p1", "retrieved_docs": docs})
    prompt = prompts.build_prompt(query, docs, [], True, result["inventory_failed"])

    assert result["inventory_failed"] is True
    assert result["inventory_units"] == []
    assert "Không suy ra tình trạng còn/hết từ tài liệu dự án" in prompt
    assert "không nói hay ngụ ý là đã hết căn" in prompt
    assert "Không khẳng định một mã căn cụ thể đang còn" in prompt


def test_document_failure_returns_a_clear_notice_when_no_other_source_can_answer(monkeypatch):
    def retrieval_down(*_args, **_kwargs):
        raise RetrievalError("qdrant offline")

    monkeypatch.setattr(agent_pipeline, "retrieve", retrieval_down)
    result = agent_pipeline._retrieve({"query": "Pháp lý và sổ hồng dự án thế nào?", "project_id": None})

    assert result == {"notice": agent_pipeline.RETRIEVAL_ERROR_MESSAGE}


def test_document_failure_does_not_block_the_live_part_of_a_mixed_question(monkeypatch):
    query = "Còn căn 2PN nào và chính sách thanh toán thế nào?"

    def retrieval_down(*_args, **_kwargs):
        raise RetrievalError("qdrant offline")

    monkeypatch.setattr(agent_pipeline, "retrieve", retrieval_down)
    monkeypatch.setattr(
        agent_pipeline,
        "lookup_inventory",
        lambda *_args, **_kwargs: [InventoryUnit("A-1205", "p1", "The Palma", "2PN", 68, 3_500_000_000, "available")],
    )

    retrieved = agent_pipeline._retrieve({"query": query, "project_id": "p1"})
    inventory = agent_pipeline._tool_call({"query": query, **retrieved})

    assert retrieved["retrieved_docs"] == []
    assert retrieved["needs_document_retrieval"] is True
    assert retrieved["needs_inventory"] is True
    assert inventory["inventory_failed"] is False
    assert [unit.unit_code for unit in inventory["inventory_units"]] == ["A-1205"]
