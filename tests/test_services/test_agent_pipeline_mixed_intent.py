from types import SimpleNamespace

from backend.ai import prompts
from backend.services import agent_pipeline
from backend.services.inventory_service import InventoryApiError, InventoryUnit


def _policy_hit() -> dict:
    return {
        "document_id": 101,
        "title": "CSBH The Beverly V64.pdf",
        "page": 2,
        "content": "Can 2PN duoc chiet khau 5% khi thanh toan som.",
        "score": 0.9,
    }


def _available_2pn() -> InventoryUnit:
    return InventoryUnit(
        unit_code="OP3-BE1-1205",
        project_id="ocean-park-3",
        subdivision="The Beverly",
        unit_type="2PN",
        area_m2=68.2,
        price=3_600_000_000,
        status="available",
    )


def test_mixed_inventory_and_policy_question_uses_both_sources(monkeypatch):
    query = "Co can nao 2 phong ngu va chinh sach ban hang nhu nao?"
    calls: list[str] = []

    def fake_retrieve(*_args, **_kwargs):
        calls.append("qdrant")
        return [_policy_hit()]

    def fake_inventory(project_id: str, received_query: str):
        calls.append("inventory")
        assert project_id == "ocean-park-3"
        assert received_query == query
        return [_available_2pn()]

    monkeypatch.setattr(agent_pipeline, "retrieve", fake_retrieve)
    monkeypatch.setattr(agent_pipeline, "lookup_inventory", fake_inventory)

    retrieved = agent_pipeline._retrieve({"query": query, "project_id": "ocean-park-3"})
    inventory = agent_pipeline._tool_call({"query": query, "project_id": "ocean-park-3", **retrieved})
    prompt = prompts.build_prompt(
        query,
        retrieved["retrieved_docs"],
        inventory["inventory_units"],
        retrieved["needs_inventory"],
        inventory["inventory_failed"],
    )

    assert calls == ["qdrant", "inventory"]
    assert retrieved["needs_document_retrieval"] is True
    assert retrieved["needs_inventory"] is True
    assert "CSBH The Beverly V64.pdf" in prompt
    assert "OP3-BE1-1205" in prompt


def test_budget_recommendation_reads_documents_and_live_inventory(monkeypatch):
    """Regression for customer chat: a budget filter must not take inventory-only routing.

    The uploaded project documents carry published price ranges, while the inventory API
    carries current availability; the answer needs both.
    """
    calls: list[str] = []

    def fake_retrieve(*_args, **_kwargs):
        calls.append("qdrant")
        return [_policy_hit()]

    monkeypatch.setattr(agent_pipeline, "retrieve", fake_retrieve)

    result = agent_pipeline._retrieve(
        {
            "query": "tư vấn cho tôi căn dưới 3 tỷ",
            "project_id": None,
        }
    )

    assert calls == ["qdrant"]
    assert result["needs_document_retrieval"] is True
    assert result["needs_inventory"] is True
    assert result["retrieved_docs"] == [_policy_hit()]


def test_parent_project_retrieval_scope_expands_from_catalogue_metadata():
    rows = [
        SimpleNamespace(id="parent", details={"project": {}}),
        SimpleNamespace(id="child-a", details={"project": {"parent_project_id": "parent"}}),
        SimpleNamespace(id="unrelated", details={"project": {"parent_project_id": "somewhere-else"}}),
    ]

    class _Query:
        def all(self):
            return rows

    class _Db:
        def query(self, _model):
            return _Query()

    assert agent_pipeline._rag_project_scope_ids(_Db(), "parent") == ["parent", "child-a"]


def test_mixed_question_keeps_policy_context_when_inventory_fails(monkeypatch):
    state = {
        "query": "Co can 2PN va chinh sach ban hang the nao?",
        "project_id": "ocean-park-3",
        "retrieved_docs": [_policy_hit()],
    }

    monkeypatch.setattr(
        agent_pipeline,
        "lookup_inventory",
        lambda *_args: (_ for _ in ()).throw(InventoryApiError("offline")),
    )

    result = agent_pipeline._tool_call(state)

    assert result["inventory_failed"] is True
    assert result["inventory_units"] == []
    assert "notice" not in result


def test_session_without_project_still_reaches_live_inventory(monkeypatch):
    """Bug trong ảnh chụp màn hình: form tạo phiên bỏ bước chọn dự án nên session không
    còn project_id, `_tool_call` thoát sớm và mọi câu hỏi tồn kho đều rơi vào
    "Live Inventory unavailable" dù API vẫn chạy tốt."""
    received: dict = {}

    def fake_inventory(project_id, query):
        received["project_id"] = project_id
        return [_available_2pn()]

    monkeypatch.setattr(agent_pipeline, "lookup_inventory", fake_inventory)

    result = agent_pipeline._tool_call(
        {
            "query": "Có căn nào 2 phòng ngủ và chính sách bán hàng như nào?",
            "project_id": None,
            "retrieved_docs": [_policy_hit()],
        }
    )

    assert received["project_id"] is None
    assert result["inventory_failed"] is False
    assert [unit.unit_code for unit in result["inventory_units"]] == ["OP3-BE1-1205"]


def test_prompt_keeps_unavailable_notice_when_lookup_cannot_resolve_a_project(monkeypatch):
    """Không resolve được dự án nào thì vẫn phải nói thẳng là không tra được tồn kho,
    tuyệt đối không suy ra số căn từ tài liệu tĩnh."""
    monkeypatch.setattr(
        agent_pipeline,
        "lookup_inventory",
        lambda *_args: (_ for _ in ()).throw(InventoryApiError("no project id")),
    )

    result = agent_pipeline._tool_call(
        {"query": "Có căn nào 2 phòng ngủ?", "project_id": None, "retrieved_docs": [_policy_hit()]}
    )
    prompt = prompts.build_prompt("Có căn nào 2 phòng ngủ?", [_policy_hit()], [], True, result["inventory_failed"])

    assert result["inventory_failed"] is True
    assert "TỒN KHO THEO MÃ CĂN: chưa tra được" in prompt
    assert "Không suy ra tình trạng còn/hết từ tài liệu dự án" in prompt
    assert "không nói hay ngụ ý là đã hết căn" in prompt


def test_internal_prompt_requires_every_requested_subject_to_be_answered():
    prompt = prompts.build_prompt(
        "Cho tôi giá và diện tích căn 2PN.",
        [_policy_hit()],
        [],
        False,
        False,
    )

    assert "phải trả lời đủ từng ý" in prompt
    assert "rà soát toàn bộ các đoạn và bảng" in prompt


def test_inventory_prompt_and_verifier_receive_every_mockapi_field():
    unit = _available_2pn()

    prompt = prompts.build_prompt("Cho tôi toàn bộ dữ liệu căn này", [], [unit], True, False)
    verifier_fact = prompts.format_unit_for_verifier(unit)

    for field_value in (
        "unit_code=OP3-BE1-1205",
        "project_id=ocean-park-3",
        "subdivision=The Beverly",
        "unit_type=2PN",
        "area_m2=68.2",
        "price_vnd=3600000000",
        "status=available",
    ):
        assert field_value in prompt
        assert field_value in verifier_fact


def test_prompt_explains_pn_br_alias_when_source_uses_english_label():
    doc = {
        **_policy_hit(),
        "content": "|2BR|64,3-69,9|5,774-7,273|\n|2BR+|69,8-76,2|6,743-7,916|",
    }

    prompt = prompts.build_prompt("Giá căn 2PN và 2PN+1?", [doc], [], False, False)

    assert "2PN = 2BR" in prompt
    assert "2PN+1 = 2BR+" in prompt
    assert "|2BR (2PN)|" in prompt
    assert "|2BR+ (2PN+1)|" in prompt


def test_prompt_omits_bedroom_alias_note_when_it_is_irrelevant():
    prompt = prompts.build_prompt("Tiến độ bàn giao?", [_policy_hit()], [], False, False)

    assert "QUY ƯỚC KÝ HIỆU" not in prompt
