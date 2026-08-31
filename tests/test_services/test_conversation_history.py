"""Conversation memory: prior turns now reach both the generation prompt and the
retrieval embedding, and the semantic cache is disabled once there's any history —
see agent_pipeline.run_pipeline's `history` param and prompts.build_prompt.

Regression coverage for the bug reported live: "Có căn 2PN nào không?" -> "Giá bao
nhiêu?" answered as if the second question had no relation to the first, because
run_pipeline never received anything but the bare current-turn query.
"""

from backend.ai import prompts
from backend.core.enums import DocumentVisibility, MessageSender
from backend.services import agent_pipeline


def _history():
    return [
        {"sender": MessageSender.CUSTOMER, "content": "Có căn 2PN nào không?"},
        {"sender": MessageSender.AGENT, "content": "Dạ hiện có 3 căn 2PN, giá từ 3.2 đến 3.8 tỷ ạ."},
    ]


def test_build_prompt_includes_history_transcript():
    prompt = prompts.build_prompt("Giá bao nhiêu?", [], [], False, False, is_public=True, history=_history())

    assert "LỊCH SỬ HỘI THOẠI" in prompt
    assert "Có căn 2PN nào không?" in prompt
    assert "3.2 đến 3.8 tỷ" in prompt


def test_build_prompt_omits_history_section_when_none():
    prompt = prompts.build_prompt("Giá bao nhiêu?", [], [], False, False, is_public=True, history=None)

    assert "LỊCH SỬ HỘI THOẠI" not in prompt


def test_build_prompt_public_labels_differ_from_internal():
    public_prompt = prompts.build_prompt("Giá bao nhiêu?", [], [], False, False, is_public=True, history=_history())
    internal_prompt = prompts.build_prompt("Giá bao nhiêu?", [], [], False, False, is_public=False, history=_history())

    assert "Khách: Có căn 2PN nào không?" in public_prompt
    assert "Em: Dạ hiện có 3 căn 2PN" in public_prompt
    assert "Bạn: Dạ hiện có 3 căn 2PN" in internal_prompt
    assert "Em:" not in internal_prompt


def test_build_prompt_warns_against_repeating_the_ai_own_question():
    """Regression for the bug reported live, still reproducing AFTER the prose-only
    anti-repetition rule shipped: AI ends a turn with a CTA question ("...diện tích chi
    tiết không ạ?"), customer replies "có", and with nothing new to add the AI repeated the
    exact same sentence and question again. A general policy statement buried among many
    other rules wasn't reliably enough — quoting the exact prior text is a stronger,
    code-level backstop."""
    history = [
        {"sender": MessageSender.CUSTOMER, "content": "Tôi xem The Pavilion"},
        {
            "sender": MessageSender.AGENT,
            "content": "Dạ căn 1PN diện tích 35-48m2 ạ. Anh chị muốn xem thêm diện tích chi tiết không ạ?",
        },
    ]

    prompt = prompts.build_prompt("có", [], [], False, False, is_public=True, history=history)

    assert "TUYỆT ĐỐI không lặp lại" in prompt
    assert "Anh chị muốn xem thêm diện tích chi tiết không ạ?" in prompt


def test_build_prompt_has_no_repeat_warning_when_last_ai_turn_is_a_statement():
    history = [
        {"sender": MessageSender.CUSTOMER, "content": "Có căn 2PN nào không?"},
        {"sender": MessageSender.AGENT, "content": "Dạ hiện có 3 căn 2PN, giá từ 3.2 đến 3.8 tỷ ạ."},
    ]

    prompt = prompts.build_prompt("Giá bao nhiêu?", [], [], False, False, is_public=True, history=history)

    assert "TUYỆT ĐỐI không lặp lại" not in prompt


def test_build_prompt_has_no_repeat_warning_with_no_history():
    prompt = prompts.build_prompt("Giá bao nhiêu?", [], [], False, False, is_public=True, history=None)

    assert "TUYỆT ĐỐI không lặp lại" not in prompt


def test_retrieval_query_folds_in_last_customer_turn():
    expanded = agent_pipeline._retrieval_query("Giá bao nhiêu?", _history())

    assert expanded == "Có căn 2PN nào không? Giá bao nhiêu?"


def test_retrieval_query_unchanged_with_no_history():
    assert agent_pipeline._retrieval_query("Giá bao nhiêu?", None) == "Giá bao nhiêu?"
    assert agent_pipeline._retrieval_query("Giá bao nhiêu?", []) == "Giá bao nhiêu?"


def test_retrieval_query_ignores_agent_only_history():
    history = [{"sender": MessageSender.AGENT, "content": "Dạ em chào anh chị ạ."}]

    assert agent_pipeline._retrieval_query("Giá bao nhiêu?", history) == "Giá bao nhiêu?"


def test_retrieval_query_works_for_a_sale_turn_too():
    """Not gated on clearance — sale_live.py's /suggest co-pilot runs a CUSTOMER's message
    at INTERNAL clearance, so "the asker's own turn" can't be derived from clearance alone."""
    history = [{"sender": MessageSender.SALE, "content": "Có căn 2PN nào không?"}]

    assert agent_pipeline._retrieval_query("Giá bao nhiêu?", history) == "Có căn 2PN nào không? Giá bao nhiêu?"


def test_retrieval_query_folds_in_the_ai_own_question():
    """Regression for the bug reported live: AI asks '...các khoản chiết khấu này không
    ạ?', customer replies just 'có', and retrieval must not fall back to whatever topic a
    customer turn several messages earlier was about — it has to pick up the topic the AI
    itself just introduced, or the reply retrieves against the wrong thing entirely."""
    history = [
        {"sender": MessageSender.CUSTOMER, "content": "3.5 tỉ"},
        {
            "sender": MessageSender.AGENT,
            "content": "Dạ với 3,5 tỷ có vài lựa chọn phù hợp. Anh chị có muốn tìm hiểu kỹ hơn về các khoản chiết khấu này không ạ?",
        },
    ]

    expanded = agent_pipeline._retrieval_query("có", history)

    assert "các khoản chiết khấu này không ạ?" in expanded
    assert expanded.endswith(" có")


def test_retrieval_query_skips_folding_for_a_self_sufficient_query():
    """Regression for the bug reported live: switching topic with "Tôi xem giá Sapphire 2"
    right after asking about "hồ bơi" got folded into "thế có hồ bơi không Tôi xem giá
    Sapphire 2" — the pool keyword buried the actual Sapphire 2 price docs. A query that
    already names its own project + topic must not be diluted by the previous one."""
    history = [{"sender": MessageSender.CUSTOMER, "content": "Thế có hồ bơi không?"}]

    assert agent_pipeline._retrieval_query("Tôi xem giá Sapphire 2", history) == "Tôi xem giá Sapphire 2"


def test_retrieval_query_reaches_past_an_unrelated_intervening_turn():
    """Regression for the bug reported live: "Tôi có ngân sách 3 tỷ, muốn mua The Pavilion"
    (turn 1), then an unrelated parking question (turn 3), then "Thế tôi muốn mua để đầu tư
    thì sao?" (turn 5) — folding only the immediately preceding turn lost "The Pavilion" and
    "3 tỷ" entirely, so retrieval drifted to a different project's investment-potential doc.
    "Thế ... thì sao?" is 9 words (past _SHORT_QUERY_WORD_LIMIT) but still names no topic of
    its own, so it needs folding via the continuation-prefix path, not the short-query one.
    """
    history = [
        {"sender": MessageSender.CUSTOMER, "content": "Tôi có ngân sách 3 tỷ, muốn mua The Pavilion"},
        {"sender": MessageSender.AGENT, "content": "Dạ có căn 1PN phù hợp ạ. Anh chị muốn xem thêm không ạ?"},
        {"sender": MessageSender.CUSTOMER, "content": "Khu này có bãi đỗ xe không?"},
        {
            "sender": MessageSender.AGENT,
            "content": "Dạ The Pavilion chưa có dữ liệu bãi đỗ xe. Anh chị muốn tìm hiểu thêm tiện ích khác không ạ?",
        },
    ]

    expanded = agent_pipeline._retrieval_query("Thế tôi muốn mua để đầu tư thì sao?", history)

    assert "The Pavilion" in expanded
    assert "3 tỷ" in expanded


def test_retrieval_query_ignores_ai_statement_that_is_not_a_question():
    """A closing statement (no '?') carries no topic worth folding in — only a real
    question is something a short reply could be answering."""
    history = [
        {"sender": MessageSender.CUSTOMER, "content": "Có căn 2PN nào không?"},
        {"sender": MessageSender.AGENT, "content": "Dạ hiện có 3 căn 2PN, giá từ 3.2 đến 3.8 tỷ ạ."},
    ]

    assert agent_pipeline._retrieval_query("Giá bao nhiêu?", history) == "Có căn 2PN nào không? Giá bao nhiêu?"


def test_retrieve_separates_history_expansion_from_current_turn_constraints(monkeypatch):
    seen = {}

    def fake_retrieve(query, visibility, project_id, top_k, *, focus_query=None, **kwargs):
        seen.update(query=query, focus_query=focus_query)
        return []

    monkeypatch.setattr(agent_pipeline, "retrieve", fake_retrieve)
    state = {
        "query": "Còn 3PN thì sao?",
        "history": [{"sender": MessageSender.CUSTOMER, "content": "Cho tôi xem căn 2PN"}],
        "project_id": "the-palma",
        "clearance": DocumentVisibility.INTERNAL,
    }

    agent_pipeline._retrieve(state)

    assert "2PN" in seen["query"]
    assert seen["query"].endswith("Còn 3PN thì sao?")
    assert seen["focus_query"] == "Còn 3PN thì sao?"


def test_inventory_context_uses_recent_human_turns_only_newest_first():
    history = [
        {"sender": MessageSender.SALE, "content": "Còn căn 2 ngủ ở The Sapphire không?"},
        {"sender": MessageSender.AGENT, "content": "Hiện có 6 căn, giá từ 2,82 tỷ."},
        {"sender": MessageSender.SALE, "content": "Diện tích từ 45 đến 70 m2 thì sao?"},
        {"sender": MessageSender.AGENT, "content": "Để tôi kiểm tra."},
    ]

    assert agent_pipeline._inventory_context_queries(history) == [
        "Diện tích từ 45 đến 70 m2 thì sao?",
        "Còn căn 2 ngủ ở The Sapphire không?",
    ]


def test_inventory_field_follow_up_keeps_live_tool_routing(monkeypatch):
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *_args, **_kwargs: [])
    state = {
        "query": "Giá bao nhiêu?",
        "history": [
            {"sender": MessageSender.SALE, "content": "Còn căn 2 ngủ ở The Sapphire không?"},
            {"sender": MessageSender.AGENT, "content": "Hiện có 6 căn."},
        ],
        "project_id": None,
        "clearance": DocumentVisibility.INTERNAL,
    }

    result = agent_pipeline._retrieve(state)

    assert result["needs_inventory"] is True


def test_verify_scores_against_the_history_expanded_query(monkeypatch):
    """Regression for the bug reported live: retrieval/generate picked up the history fix,
    but _verify still judged the bare "có" against a correct, on-topic draft answer and
    failed it as irrelevant — discarding a good answer for the low-confidence fallback."""
    seen_queries = []

    def _fake_score_answer(query, draft_answer, context):
        seen_queries.append(query)
        return agent_pipeline.verifier_service.VerifierResult(faithfulness=1.0, relevancy=1.0)

    monkeypatch.setattr(agent_pipeline.verifier_service, "score_answer", _fake_score_answer)

    history = [
        {"sender": MessageSender.CUSTOMER, "content": "3.5 tỉ"},
        {
            "sender": MessageSender.AGENT,
            "content": "Dạ với 3,5 tỷ có vài lựa chọn phù hợp. Anh chị có muốn tìm hiểu kỹ hơn về các khoản chiết khấu này không ạ?",
        },
    ]
    state = {
        "query": "có",
        "history": history,
        "draft_answer": "Dạ hiện chiết khấu 5% cho khách thanh toán sớm ạ.",
        "retrieved_docs": [{"content": "Chính sách chiết khấu: 5% cho thanh toán trước hạn."}],
    }

    agent_pipeline._verify(state)

    assert len(seen_queries) == 1
    assert "các khoản chiết khấu này không ạ?" in seen_queries[0]


def test_cache_check_skips_lookup_when_history_present(monkeypatch):
    calls = []
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **kw: calls.append(1))

    result = agent_pipeline._cache_check({"query": "Giá bao nhiêu?", "history": _history()})

    assert result == {"used_cache": False}
    assert calls == []


def test_cache_check_still_looks_up_with_no_history(monkeypatch):
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **kw: None)

    result = agent_pipeline._cache_check({"query": "Giá bao nhiêu?", "history": []})

    assert result == {"used_cache": False}


def test_run_pipeline_caps_history_to_max_messages(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(agent_pipeline, "_get_graph", lambda: _FakeGraphCapturingHistory(captured))

    long_history = [{"sender": MessageSender.CUSTOMER, "content": str(i)} for i in range(20)]
    agent_pipeline.run_pipeline("Giá bao nhiêu?", clearance=DocumentVisibility.PUBLIC, history=long_history)

    assert len(captured["history"]) == agent_pipeline.MAX_HISTORY_MESSAGES
    assert captured["history"][-1]["content"] == "19"


class _FakeGraphCapturingHistory:
    def __init__(self, captured: dict):
        self._captured = captured

    def invoke(self, initial):
        self._captured["history"] = initial.get("history")
        return {"notice": "stub"}
