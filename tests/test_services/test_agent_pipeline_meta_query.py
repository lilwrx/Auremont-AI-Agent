"""Questions about the conversation itself must not be judged against documents.

"Tôi vừa hỏi về phân khu nào" is answered from the history block in the prompt — no
retrieved document can ever ground it, so the Verifier scores faithfulness 0.0 however
correct the answer is, and the pipeline replaces it with "Không đủ thông tin, liên hệ
Admin." These tests pin the routing that avoids that.
"""

from backend.services import agent_pipeline


def _doc_hit() -> dict:
    return {
        "document_id": 42,
        "title": "The_Zenpark_VHOP_ThongTinDuAn_Full.pdf",
        "page": 1,
        "content": "Phan khu The Zenpark toa lac tai cua ngo phia Bac Vinhomes Ocean Park.",
        "score": 0.88,
    }


def _history() -> list[dict]:
    return [
        {"sender": "sale", "content": "the zenpark ở đâu"},
        {"sender": "agent", "content": "Phân khu The Zenpark tọa lạc tại cửa ngõ phía Bắc..."},
    ]


def test_meta_query_skips_verify():
    """The regression this whole module exists for: with history present, a question about
    the transcript routes straight to RiskCheck instead of the Verifier."""
    state = {
        "query": "tôi vừa hỏi về phân khu nào",
        "history": _history(),
        "draft_answer": "Bạn vừa hỏi về phân khu The Zenpark.",
        "retrieved_docs": [_doc_hit()],
    }

    assert agent_pipeline._route_after_generate(state) == "risk_check"


def test_meta_query_without_history_still_verifies():
    """Nothing to recall means nothing to exempt — the answer faces the normal checks."""
    state = {
        "query": "tôi vừa hỏi về phân khu nào",
        "history": [],
        "draft_answer": "Bạn vừa hỏi về phân khu The Zenpark.",
        "retrieved_docs": [_doc_hit()],
    }

    assert agent_pipeline._route_after_generate(state) == "verify"


def test_project_question_with_history_still_verifies():
    """The costly direction to get wrong: an ordinary project question must not skip
    verification just because the session happens to have history."""
    state = {
        "query": "giá căn 2PN The Zenpark bao nhiêu",
        "history": _history(),
        "draft_answer": "Căn 2PN có giá từ 3,6 tỷ.",
        "retrieved_docs": [_doc_hit()],
    }

    assert agent_pipeline._route_after_generate(state) == "verify"


def test_meta_query_notice_still_stops():
    """A generation failure short-circuits ahead of the meta-query branch, as before."""
    state = {
        "query": "tôi vừa hỏi về phân khu nào",
        "history": _history(),
        "notice": agent_pipeline.GENERATION_ERROR_MESSAGE,
    }

    assert agent_pipeline._route_after_generate(state) == "stop"
