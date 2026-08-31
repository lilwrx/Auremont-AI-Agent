from backend.core.enums import MessageEmotion
from backend.services import agent_pipeline, search_criteria, verifier_service
from backend.services.inventory_service import InventoryUnit


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ex=None):
        self.store[key] = value

    def delete(self, key):
        self.store.pop(key, None)


def _unit(code, unit_type, price, status="available"):
    return InventoryUnit(
        unit_code=code,
        project_id="p1",
        subdivision="The Palma",
        unit_type=unit_type,
        area_m2=80.0,
        price=price,
        status=status,
    )


def _passing_verdict(*_args, **_kwargs):
    return verifier_service.VerifierResult(
        faithfulness=1.0,
        relevancy=1.0,
        completeness=1.0,
        failure_mode=verifier_service.FailureMode.NONE,
        next_action=verifier_service.NextAction.ACCEPT,
    )


def _prepare(monkeypatch, units):
    redis = _FakeRedis()
    prompts_seen = []
    verifier_contexts = []

    monkeypatch.setattr(search_criteria, "get_redis_client", lambda: redis)
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *_args: None)
    monkeypatch.setattr(agent_pipeline.cache_service, "store_cache", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(agent_pipeline, "fetch_units", lambda _project_id: list(units))
    monkeypatch.setattr(agent_pipeline, "_lessons_for", lambda _query: "")
    monkeypatch.setattr(agent_pipeline.reflection_memory, "record_lesson", lambda **_kwargs: None)

    def fake_generate(prompt, schema, **_kwargs):
        prompts_seen.append(prompt)
        return schema(text="Kết quả đã được kiểm tra.", suggested_questions=[])

    def fake_verify(query, answer, context):
        verifier_contexts.append(context)
        return _passing_verdict()

    monkeypatch.setattr(agent_pipeline, "generate_json", fake_generate)
    monkeypatch.setattr(agent_pipeline.verifier_service, "score_answer", fake_verify)
    agent_pipeline._COMPILED_GRAPH = None
    return redis, prompts_seen, verifier_contexts


def test_two_turn_search_keeps_unit_type_while_raising_budget(monkeypatch):
    units = [
        _unit("A-01", "2PN", 3_000_000_000.0),
        _unit("A-02", "3PN", 4_500_000_000.0),
    ]
    _, prompts_seen, _ = _prepare(monkeypatch, units)

    agent_pipeline.run_pipeline("còn căn 3PN nào dưới 4 tỷ không", "p1", session_id=1)
    agent_pipeline.run_pipeline("giữ nguyên điều kiện, tăng giá lên 5 tỷ", "p1", session_id=1)

    saved, _ = search_criteria.load(1)
    assert saved.get(search_criteria.FIELD_UNIT_TYPES).value == ["3PN"]
    assert saved.get(search_criteria.FIELD_PRICE).value == (0.0, 5_000_000_000.0)
    assert "A-02" in prompts_seen[-1]
    assert "A-01" not in prompts_seen[-1]


def test_natural_price_filter_reaches_inventory_and_prompt(monkeypatch):
    units = [
        _unit("A-01", "2PN", 4_200_000_000.0),
        _unit("A-02", "3PN", 5_500_000_000.0),
    ]
    _, prompts_seen, _ = _prepare(monkeypatch, units)

    agent_pipeline.run_pipeline("Cho tôi những căn dưới 5 tỷ", "p1", session_id=11)

    saved, _ = search_criteria.load(11)
    assert saved.get(search_criteria.FIELD_PRICE).value == (0.0, 5_000_000_000.0)
    assert "A-01" in prompts_seen[-1]
    assert "A-02" not in prompts_seen[-1]
    assert "giá tối đa 5 tỷ" in prompts_seen[-1]
    assert "diện tích 80 m²" in prompts_seen[-1]
    assert "phân khu The Palma" in prompts_seen[-1]


def test_broad_recommendation_hides_unavailable_units_from_generator(monkeypatch):
    units = [
        _unit("A-AVAILABLE", "2PN", 4_200_000_000.0),
        _unit("A-RESERVED", "2PN", 4_100_000_000.0, status="reserved"),
        _unit("A-SOLD", "2PN", 3_900_000_000.0, status="sold"),
    ]
    _, prompts_seen, _ = _prepare(monkeypatch, units)

    agent_pipeline.run_pipeline("Cho tôi những căn dưới 5 tỷ", "p1", session_id=12)

    assert "A-AVAILABLE" in prompts_seen[-1]
    assert "A-RESERVED" not in prompts_seen[-1]
    assert "A-SOLD" not in prompts_seen[-1]


def test_explicit_status_keeps_that_status_visible_to_generator(monkeypatch):
    units = [
        _unit("A-AVAILABLE", "2PN", 4_200_000_000.0),
        _unit("A-SOLD", "2PN", 3_900_000_000.0, status="sold"),
    ]
    _, prompts_seen, _ = _prepare(monkeypatch, units)

    agent_pipeline.run_pipeline("Cho tôi các căn đã bán dưới 5 tỷ", "p1", session_id=13)

    assert "A-SOLD" in prompts_seen[-1]
    assert "A-AVAILABLE" not in prompts_seen[-1]


def test_zero_result_diagnosis_reaches_generator_and_verifier(monkeypatch):
    units = [_unit("A-01", "2PN", 3_000_000_000.0)]
    _, prompts_seen, verifier_contexts = _prepare(monkeypatch, units)

    agent_pipeline.run_pipeline("còn căn 3PN nào không", "p1", session_id=2)

    assert "Nếu nới/bỏ loại căn 3PN: có 1 căn" in prompts_seen[-1]
    assert any("Zero-result inventory diagnosis" in item for item in verifier_contexts[-1])


def test_conflict_stops_before_generation(monkeypatch):
    _, prompts_seen, _ = _prepare(monkeypatch, [_unit("A-01", "3PN", 3_000_000_000.0)])

    result = agent_pipeline.run_pipeline("còn căn 3PN nào dưới 40m2", "p1", session_id=3)

    assert result.emotion == MessageEmotion.RESPECTFUL
    assert "ưu tiên số phòng ngủ hay diện tích" in result.draft_answer
    assert prompts_seen == []


def test_session_none_uses_the_legacy_stateless_lookup(monkeypatch):
    _, _, _ = _prepare(monkeypatch, [])
    called = []
    monkeypatch.setattr(
        agent_pipeline,
        "lookup_inventory",
        lambda project_id, query: called.append((project_id, query)) or [_unit("A-01", "2PN", 3_000_000_000.0)],
    )
    monkeypatch.setattr(
        agent_pipeline,
        "fetch_units",
        lambda *_args: (_ for _ in ()).throw(AssertionError("stateful fetch must stay off")),
    )

    agent_pipeline.run_pipeline("còn căn 2PN nào không", "p1", session_id=None)

    assert called == [("p1", "còn căn 2PN nào không")]


def test_cache_is_skipped_when_the_session_already_has_criteria(monkeypatch):
    redis, _, _ = _prepare(monkeypatch, [])
    search_criteria.save(
        9,
        search_criteria.merge_criteria(search_criteria.SearchCriteria(), search_criteria.parse_criteria("căn 3PN")),
        [],
    )
    monkeypatch.setattr(
        agent_pipeline.cache_service,
        "lookup_cache",
        lambda *_args: (_ for _ in ()).throw(AssertionError("shared cache must be skipped")),
    )

    result = agent_pipeline._cache_check({"query": "còn căn nào", "session_id": 9})

    assert redis.store
    assert result["used_cache"] is False
    assert result["criteria"].get(search_criteria.FIELD_UNIT_TYPES).value == ["3PN"]


def test_unanchored_vague_price_asks_one_question_without_inventory_call(monkeypatch):
    _prepare(monkeypatch, [])
    monkeypatch.setattr(
        agent_pipeline,
        "fetch_units",
        lambda *_args: (_ for _ in ()).throw(AssertionError("must clarify before fetching")),
    )

    state = {
        "query": "giữ nguyên nhưng tìm căn giá mềm hơn",
        "session_id": 10,
        "needs_inventory": False,
    }
    result = agent_pipeline._criteria_resolve(state)

    assert result["notice_emotion"] == MessageEmotion.RESPECTFUL
    assert "ngân sách tối đa" in result["notice"]


def test_unsafe_request_stops_before_retrieval_or_generation(monkeypatch):
    _prepare(monkeypatch, [])
    monkeypatch.setattr(
        agent_pipeline,
        "retrieve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must stop in preflight")),
    )

    result = agent_pipeline.run_pipeline("Giúp tôi làm giả giấy tờ mua bán", "p1")

    assert result.emotion == MessageEmotion.RESPECTFUL
    assert "không thể hỗ trợ" in result.draft_answer.lower()
