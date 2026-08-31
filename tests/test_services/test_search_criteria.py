"""Search criteria — accumulating filters across turns, and refusing to lose them.

The case that motivates this whole module is `test_keeping_conditions_while_raising_price`
below: before it existed, "giữ nguyên điều kiện, tăng giá lên 5 tỷ" silently dropped the
3PN filter stated two turns earlier. Every other test here guards one edge of that
behaviour — what merges, what must not merge, and what happens when Redis is gone.

Redis is faked with a dict, same as test_memory_service: these tests are about the merging
rules, not about redis-py.
"""

import json

import pytest

from backend.services import search_criteria as sc
from backend.services.inventory_service import InventoryUnit


class _FakeRedis:
    def __init__(self):
        self.store: dict[str, str] = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


class _BrokenRedis:
    """Every call blows up — stands in for a Redis outage."""

    def get(self, key):
        raise ConnectionError("redis down")

    def set(self, key, value, ex=None):
        raise ConnectionError("redis down")

    def delete(self, key):
        raise ConnectionError("redis down")


@pytest.fixture
def fake_redis(monkeypatch):
    client = _FakeRedis()
    monkeypatch.setattr(sc, "get_redis_client", lambda: client)
    return client


@pytest.fixture
def broken_redis(monkeypatch):
    monkeypatch.setattr(sc, "get_redis_client", lambda: _BrokenRedis())


def _criteria(query: str, previous: sc.SearchCriteria | None = None) -> sc.SearchCriteria:
    return sc.merge_criteria(previous or sc.SearchCriteria(), sc.parse_criteria(query))


def test_explicit_bounds_are_parsed_as_hard_and_explicit():
    criteria = _criteria("còn căn 3PN nào dưới 4 tỷ không")

    assert criteria.get("unit_types").value == ["3PN"]
    assert criteria.get("price").value == (0.0, 4_000_000_000.0)
    assert criteria.get("price").strength == sc.Strength.HARD
    assert criteria.get("price").source == sc.Source.EXPLICIT


def test_vague_price_becomes_a_band_marked_inferred():
    """'Tầm 3 tỷ' phải thành khoảng đo được, và đánh dấu là hệ thống tự suy."""
    criteria = _criteria("tìm căn tầm 3 tỷ")

    assert criteria.get("price").value == (2_550_000_000.0, 3_450_000_000.0)
    assert criteria.get("price").source == sc.Source.INFERRED


def test_area_is_soft_unless_the_sentence_compels_it():
    """Ai nói 'phải' thì không được nhận căn bỏ qua điều đó; nhắc thoáng qua thì được."""
    assert _criteria("tìm căn 80m2").get("area").strength == sc.Strength.SOFT
    assert _criteria("phải có ít nhất 80m2").get("area").strength == sc.Strength.HARD


def test_adjustment_phrasing_sets_a_ceiling_in_both_directions():
    """'Tăng giá lên 5 tỷ' là nới trần lên 5 tỷ, KHÔNG phải đòi căn từ 5 tỷ trở lên."""
    assert _criteria("tăng giá lên 5 tỷ").get("price").value == (0.0, 5_000_000_000.0)
    assert _criteria("giảm xuống 3 tỷ").get("price").value == (0.0, 3_000_000_000.0)


def test_move_in_now_infers_available_status():
    criteria = _criteria("có căn nào ở được ngay không")

    assert criteria.get("statuses").value == ["available"]
    assert criteria.get("statuses").source == sc.Source.INFERRED


def test_purpose_and_household_are_kept_as_advisory_context():
    criteria = _criteria("Tôi mua để ở cho gia đình 4 người")

    assert criteria.purpose == "living"
    assert criteria.household_size == 4
    assert "Mục đích: để ở" in sc.format_criteria(criteria)
    assert "Số người ở: 4" in sc.format_criteria(criteria)


def test_supported_sort_language_is_parsed():
    assert _criteria("sắp xếp giá thấp đến cao").sort_by == "price_asc"
    assert _criteria("cho tôi căn rộng nhất trước").sort_by == "area_desc"


def test_keeping_conditions_while_raising_price():
    """Ca hồi quy chính của cases.md §20.

    Trước khi có module này, lượt thứ hai parse lại từ đầu và mất hẳn 3PN — khách phải
    nhắc lại toàn bộ điều kiện mỗi lượt, đúng thứ họ vừa bảo là "giữ nguyên".
    """
    first = _criteria("còn căn 3PN nào dưới 4 tỷ không")
    second = _criteria("giữ nguyên điều kiện, tăng giá lên 5 tỷ", first)

    assert second.get("unit_types").value == ["3PN"], "3PN phải sống sót qua lượt đổi giá"
    assert second.get("price").value == (0.0, 5_000_000_000.0)


def test_dropping_one_requirement_leaves_the_rest():
    first = _criteria("căn 3PN dưới 4 tỷ")
    second = _criteria("bỏ yêu cầu 3PN", first)

    assert second.get("unit_types") is None
    assert second.get("price").value == (0.0, 4_000_000_000.0)


def test_reset_clears_everything():
    first = _criteria("căn 3PN dưới 4 tỷ")

    assert _criteria("xoá toàn bộ bộ lọc", first).is_empty()


def test_cheaper_resolves_against_the_existing_ceiling():
    """'Rẻ hơn' chỉ có nghĩa khi đã có mức trần để bước xuống."""
    first = _criteria("căn 2PN dưới 5 tỷ")
    second = _criteria("có căn nào rẻ hơn không", first)

    assert second.get("price").value == (0.0, 4_000_000_000.0)
    assert second.get("price").source == sc.Source.INFERRED


def test_cheaper_with_no_anchor_is_left_unresolved():
    """Không có gì để neo vào thì phải hỏi lại, không được bịa ra một mức giá."""
    delta = sc.parse_criteria("tìm căn giá mềm")

    assert "giá" in delta.unresolved_vague
    assert sc.merge_criteria(sc.SearchCriteria(), delta).get("price") is None


def test_inverted_price_bounds_are_reported():
    criteria = sc.SearchCriteria(constraints=(sc.Constraint(sc.FIELD_PRICE, (5_000_000_000.0, 3_000_000_000.0)),))

    assert sc.detect_conflict(criteria) is not None


def test_bedrooms_impossible_within_area_cap_is_reported():
    assert sc.detect_conflict(_criteria("căn 3PN dưới 40m2")) is not None


def test_a_workable_search_reports_no_conflict():
    """Báo nhầm mâu thuẫn tốn của khách nguyên một lượt cho một tìm kiếm vốn chạy được."""
    assert sc.detect_conflict(_criteria("căn 3PN dưới 5 tỷ trên 80m2")) is None
    assert sc.detect_conflict(sc.SearchCriteria()) is None


def test_criteria_survive_a_round_trip(fake_redis):
    criteria = _criteria("căn 2PN trên 3 tỷ")
    sc.save(1, criteria, [])

    assert sc.load(1)[0] == criteria


def test_open_ended_bounds_serialise_as_valid_json(fake_redis):
    """`inf` viết thẳng ra JSON thành token `Infinity` — Python đọc được, phần còn lại
    của thế giới thì không. 'Trên 3 tỷ' là câu thường gặp, nên đây là ca thật."""
    sc.save(1, _criteria("căn trên 3 tỷ"), [])
    raw = fake_redis.store[sc.session_key(1)]

    assert "Infinity" not in raw
    json.loads(raw)
    assert sc.load(1)[0].get("price").value == (3_000_000_000.0, float("inf"))


def test_undo_restores_the_previous_filter(fake_redis):
    sc.resolve(1, "căn 3PN dưới 4 tỷ")
    sc.resolve(1, "tăng giá lên 6 tỷ")

    restored, _ = sc.resolve(1, "quay lại bộ lọc cũ")

    assert restored.get("price").value == (0.0, 4_000_000_000.0)


def test_undo_with_nothing_to_undo_is_harmless(fake_redis):
    current, _ = sc.resolve(1, "căn 3PN dưới 4 tỷ")
    restored, _ = sc.resolve(1, "quay lại bộ lọc cũ")

    assert restored == current


def test_identical_turns_do_not_fill_the_undo_stack(fake_redis):
    """Nếu lượt không đổi gì mà vẫn đẩy snapshot, 'quay lại bộ lọc cũ' sẽ lùi qua một
    loạt trạng thái giống hệt nhau và trông như không làm gì."""
    sc.resolve(1, "căn 3PN dưới 4 tỷ")
    sc.resolve(1, "căn 3PN dưới 4 tỷ")

    assert len(sc.load(1)[1]) <= 1


def test_conflicting_criteria_are_not_persisted(fake_redis):
    """Giữ bản hợp lệ cuối để lượt sau khách trả lời 'ưu tiên giá' còn có cái để merge."""
    sc.resolve(1, "căn 2PN dưới 5 tỷ")
    sc.resolve(1, "căn 3PN dưới 40m2")

    assert sc.load(1)[0].get("unit_types").value == ["2PN"]


def test_no_session_means_no_state():
    """`session_id=None` là đường fail-open ngay ở tầng chữ ký: hành vi stateless như cũ."""
    criteria, _ = sc.resolve(None, "căn 3PN dưới 4 tỷ")

    assert criteria.get("unit_types").value == ["3PN"]


def test_a_dead_redis_degrades_to_no_criteria(broken_redis):
    assert sc.load(1) == (sc.SearchCriteria(), [])
    sc.save(1, _criteria("căn 3PN"), [])
    sc.clear(1)


def test_a_corrupt_value_is_ignored(fake_redis):
    fake_redis.store[sc.session_key(1)] = "{khong-phai-json"

    assert sc.load(1) == (sc.SearchCriteria(), [])


def test_no_redis_at_all_is_not_an_error(monkeypatch):
    monkeypatch.setattr(sc, "get_redis_client", lambda: None)

    assert sc.load(1) == (sc.SearchCriteria(), [])
    sc.save(1, _criteria("căn 3PN"), [])


def _unit(code, unit_type, area, price, status="available", subdivision="The Palma"):
    return InventoryUnit(
        unit_code=code,
        project_id="p1",
        subdivision=subdivision,
        unit_type=unit_type,
        area_m2=area,
        price=price,
        status=status,
    )


def test_soft_constraints_never_exclude_a_unit():
    """Ưu tiên là để xếp hạng, không phải để loại — gộp hai thứ này là cách nhanh nhất
    để trả về 0 kết quả."""
    from backend.services.inventory_service import apply_criteria

    units = [_unit("A-01", "2PN", 60.0, 3_000_000_000.0)]
    criteria = sc.SearchCriteria(constraints=(sc.Constraint(sc.FIELD_AREA, (100.0, 200.0), sc.Strength.SOFT),))

    assert apply_criteria(units, criteria) == units


def test_hard_constraints_exclude():
    from backend.services.inventory_service import apply_criteria

    units = [
        _unit("A-01", "2PN", 60.0, 3_000_000_000.0),
        _unit("A-02", "3PN", 90.0, 6_000_000_000.0),
    ]
    criteria = _criteria("căn 3PN dưới 5 tỷ")

    assert apply_criteria(units, criteria) == []


def test_advisory_fields_do_not_filter_anything():
    """Tiện ích không có trong InventoryUnit — nếu đem đi lọc sẽ khớp 0 căn và làm rỗng
    toàn bộ kết quả, thay vì được chuyển cho model đối chiếu tài liệu."""
    from backend.services.inventory_service import apply_criteria

    units = [_unit("A-01", "2PN", 60.0, 3_000_000_000.0)]
    criteria = sc.SearchCriteria(required_features=("hồ bơi",))

    assert apply_criteria(units, criteria) == units


def test_excluded_constraint_removes_matches_instead_of_selecting_them():
    from backend.services.inventory_service import apply_criteria

    units = [
        _unit("A-01", "2PN", 60.0, 3_000_000_000.0),
        _unit("A-02", "3PN", 80.0, 4_000_000_000.0),
    ]
    criteria = _criteria("không lấy căn 3PN")

    assert criteria.get(sc.FIELD_UNIT_TYPES).strength == sc.Strength.EXCLUDED
    assert [unit.unit_code for unit in apply_criteria(units, criteria)] == ["A-01"]


def test_outside_subdivision_is_local_exclusion_and_keeps_budget_positive():
    delta = sc.parse_criteria(
        "Tôi có ngân sách dưới 4 tỷ, ngoài Zenpark thì còn căn nào?",
        known_subdivisions=["The Zenpark", "The Pavilion"],
    )
    criteria = sc.merge_criteria(sc.SearchCriteria(), delta)

    assert criteria.get(sc.FIELD_PRICE).strength == sc.Strength.HARD
    subdivision = criteria.get(sc.FIELD_SUBDIVISIONS)
    assert subdivision is not None
    assert subdivision.value == ["The Zenpark"]
    assert subdivision.strength == sc.Strength.EXCLUDED


@pytest.mark.parametrize(
    "query",
    [
        "Ngoài ra, Zenpark có căn nào?",
        "Có căn nào khác ở Zenpark không?",
    ],
)
def test_non_negative_connectors_do_not_exclude_subdivision(query):
    delta = sc.parse_criteria(query, known_subdivisions=["The Zenpark"])
    subdivision = next(item for item in delta.constraints if item.field == sc.FIELD_SUBDIVISIONS)

    assert subdivision.strength == sc.Strength.SOFT


def test_typographic_area_range_and_open_ended_view_preferences_are_preserved():
    query = "Can 2PN khoang 60–70m2, uu tien huong Dong Nam va view dep"
    criteria = sc.merge_criteria(sc.SearchCriteria(), sc.parse_criteria(query))

    assert criteria.get(sc.FIELD_AREA).value == (60.0, 70.0)
    assert criteria.get(sc.FIELD_DIRECTIONS).value == ["Dong Nam"]
    assert criteria.get(sc.FIELD_DIRECTIONS).strength == sc.Strength.SOFT
    assert "view dep" in criteria.preferred_features


def test_structured_direction_and_view_preferences_rank_confirmed_then_unknown():
    from backend.services.inventory_service import apply_criteria, format_preference_coverage

    units = [
        InventoryUnit(
            "A",
            "p",
            "Zone",
            "2PN",
            65,
            3_000_000_000,
            "available",
            direction="Đông Nam",
            view_type=("hồ",),
        ),
        InventoryUnit("B", "p", "Zone", "2PN", 66, 3_100_000_000, "available"),
        InventoryUnit(
            "C",
            "p",
            "Zone",
            "2PN",
            67,
            3_200_000_000,
            "available",
            direction="Tây Bắc",
            view_type=("thành phố",),
        ),
    ]
    criteria = _criteria("căn 2PN ưu tiên hướng Đông Nam và view hồ")

    ranked = apply_criteria(units, criteria)

    assert [unit.unit_code for unit in ranked] == ["A", "B", "C"]
    coverage = format_preference_coverage(ranked, criteria)
    assert "1 căn xác nhận khớp; 1 căn thiếu dữ liệu; 1 căn xác nhận không khớp" in coverage


def test_mandatory_direction_and_view_filter_exact_inventory_fields():
    from backend.services.inventory_service import apply_criteria

    units = [
        InventoryUnit(
            "A",
            "p",
            "Zone",
            "2PN",
            65,
            3_000_000_000,
            "available",
            direction="Đông Nam",
            view_type=("hồ",),
        ),
        InventoryUnit("B", "p", "Zone", "2PN", 66, 3_100_000_000, "available"),
    ]
    criteria = _criteria("bắt buộc hướng Đông Nam và view hồ")

    assert [unit.unit_code for unit in apply_criteria(units, criteria)] == ["A"]


def test_excluded_feature_is_advisory_but_kept_for_the_prompt():
    criteria = _criteria("tránh căn gần hồ bơi")

    assert criteria.excluded_features == ("hồ bơi",)
    assert "Loại trừ: hồ bơi" in sc.format_criteria(criteria)


def test_supported_sort_is_applied_after_filtering():
    from backend.services.inventory_service import apply_criteria

    units = [
        _unit("A-02", "2PN", 80.0, 4_000_000_000.0),
        _unit("A-01", "2PN", 60.0, 3_000_000_000.0),
    ]

    by_price = apply_criteria(units, _criteria("sắp xếp giá thấp đến cao"))
    by_area = apply_criteria(units, _criteria("diện tích lớn nhất"))

    assert [unit.unit_code for unit in by_price] == ["A-01", "A-02"]
    assert [unit.unit_code for unit in by_area] == ["A-02", "A-01"]


def test_diagnosis_counts_results_after_relaxing_one_constraint():
    units = [
        _unit("A-01", "2PN", 60.0, 3_000_000_000.0),
        _unit("A-02", "3PN", 90.0, 6_000_000_000.0),
    ]
    diagnosis = sc.diagnose_zero_results(units, _criteria("căn 3PN dưới 5 tỷ"))

    assert diagnosis is not None
    assert diagnosis.total_units == 2
    assert {option.removed[0].field: option.estimated_count for option in diagnosis.relax_options} == {
        sc.FIELD_PRICE: 1,
        sc.FIELD_UNIT_TYPES: 1,
    }


def test_diagnosis_falls_back_to_relaxing_a_pair():
    units = [_unit("A-01", "2PN", 60.0, 6_000_000_000.0)]
    diagnosis = sc.diagnose_zero_results(units, _criteria("căn 3PN dưới 5 tỷ"))

    assert diagnosis is not None
    assert len(diagnosis.relax_options) == 1
    assert {item.field for item in diagnosis.relax_options[0].removed} == {
        sc.FIELD_PRICE,
        sc.FIELD_UNIT_TYPES,
    }
    assert diagnosis.relax_options[0].estimated_count == 1


def test_diagnosis_suggests_inferred_constraint_before_explicit_one():
    units = [
        _unit("A-01", "3PN", 80.0, 4_000_000_000.0, status="sold"),
        _unit("A-02", "2PN", 60.0, 3_000_000_000.0, status="available"),
    ]
    criteria = sc.SearchCriteria(
        constraints=(
            sc.Constraint(sc.FIELD_UNIT_TYPES, ["3PN"], source=sc.Source.EXPLICIT),
            sc.Constraint(sc.FIELD_STATUSES, ["available"], source=sc.Source.INFERRED),
        )
    )

    diagnosis = sc.diagnose_zero_results(units, criteria)

    assert diagnosis is not None
    assert diagnosis.relax_options[0].removed[0].field == sc.FIELD_STATUSES


def test_diagnosis_is_grounding_for_prompt_and_verifier():
    units = [_unit("A-01", "2PN", 60.0, 3_000_000_000.0)]
    diagnosis = sc.diagnose_zero_results(units, _criteria("căn 3PN"))

    rendered = sc.format_zero_result(diagnosis)
    verifier_context = sc.format_diagnosis_for_verifier(diagnosis)

    assert "1 căn" in rendered
    assert "loại căn 3PN" in rendered
    assert rendered in verifier_context


def test_mixed_included_and_excluded_property_types_remain_separate():
    criteria = _criteria("Chỉ tìm nhà phố, không lấy chung cư")
    type_constraints = [constraint for constraint in criteria.constraints if constraint.field == sc.FIELD_UNIT_TYPES]

    assert any(
        constraint.value == ["LK"] and constraint.strength == sc.Strength.HARD for constraint in type_constraints
    )
    assert any(
        constraint.value == ["CANHO"] and constraint.strength == sc.Strength.EXCLUDED for constraint in type_constraints
    )


def test_minimum_bedroom_language_matches_larger_layouts_too():
    from backend.services.inventory_service import apply_criteria

    criteria = _criteria("Cần ít nhất 3 phòng ngủ")
    units = [
        _unit("2", "2PN", 70, 1),
        _unit("3", "3PN", 90, 1),
        _unit("4", "4PN", 110, 1),
    ]

    assert [unit.unit_code for unit in apply_criteria(units, criteria)] == ["3", "4"]
    assert "từ 3PN" in sc.format_criteria(criteria)
