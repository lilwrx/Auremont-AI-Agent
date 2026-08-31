"""Verifier Agent: the four criteria and the structured verdict behind them.

The judge scores grounding (faithfulness), correctness (relevancy) and completeness, and
classifies *why* an answer failed so the retry can act on it. These tests cover the
scoring arithmetic, the coercion that keeps a sloppy judge response usable, and the
fail-closed behaviour — never the LLM call itself, which is stubbed throughout.
"""

import pytest

from backend.services import verifier_service
from backend.services.verifier_service import (
    FailureMode,
    NextAction,
    VerifierResult,
    score_answer,
)

CONTEXT = ["Căn 2PN The Palma giá từ 3,6 tỷ đồng, đã gồm VAT."]
QUERY = "Giá căn 2PN bao nhiêu?"
ANSWER = "- Căn 2PN The Palma từ 3,6 tỷ đồng, đã gồm VAT."


def _verdict(**overrides) -> VerifierResult:
    base = {
        "faithfulness": 0.9,
        "relevancy": 0.9,
        "completeness": 0.9,
        "failure_mode": FailureMode.NONE,
        "feedback": "",
        "next_action": NextAction.ACCEPT,
    }
    return VerifierResult(**(base | overrides))


@pytest.fixture
def judge(monkeypatch):
    """Thay lời gọi Gemini bằng một verdict dựng sẵn, trả về list để test soi prompt."""
    calls = []

    def _stub(verdict: VerifierResult | None):
        def _generate_json(prompt, schema, system_instruction=None):
            calls.append(prompt)
            return verdict

        monkeypatch.setattr(verifier_service, "generate_json", _generate_json)
        return calls

    return _stub


def test_score_is_the_weakest_of_the_three_criteria():
    """Điểm tổng là min: mạnh ở hai tiêu chí không cứu được tiêu chí còn lại."""
    assert _verdict(faithfulness=0.95, relevancy=0.9, completeness=0.3).score == 0.3


def test_incomplete_answer_fails_even_when_grounded_and_on_topic():
    """Trả lời đúng nhưng thiếu ý vẫn phải trượt — đây là tiêu chí completeness mới."""
    verdict = _verdict(faithfulness=1.0, relevancy=1.0, completeness=0.2)

    assert verdict.score == 0.2
    assert not verifier_service.passes_threshold(verdict)


def test_completeness_defaults_to_one_when_judge_omits_it():
    """Judge cũ (hoặc model bỏ sót field) không được biến thành điểm 0 toàn hệ thống."""
    verdict = VerifierResult(faithfulness=0.9, relevancy=0.9)

    assert verdict.completeness == 1.0
    assert verdict.score == 0.9


def test_prompt_asks_for_all_three_scores_and_the_verdict(judge):
    calls = judge(_verdict())

    score_answer(QUERY, ANSWER, CONTEXT)

    prompt = calls[0]
    for field in ("faithfulness", "relevancy", "completeness", "failure_mode", "feedback", "next_action"):
        assert field in prompt


def test_failure_mode_and_feedback_survive_to_the_caller(judge):
    judge(
        _verdict(
            faithfulness=0.2,
            failure_mode=FailureMode.HALLUCINATED_FACT,
            feedback="Câu trả lời ghi 4,1 tỷ nhưng ngữ cảnh chỉ có 3,6 tỷ.",
            next_action=NextAction.REGENERATE,
        )
    )

    result = score_answer(QUERY, ANSWER, CONTEXT)

    assert result.failure_mode is FailureMode.HALLUCINATED_FACT
    assert "3,6 tỷ" in result.feedback
    assert result.next_action is NextAction.REGENERATE


def test_unknown_failure_mode_degrades_instead_of_dropping_the_scores():
    """Mất phân loại còn hơn mất cả ba điểm số vì một nhãn lạ."""
    verdict = VerifierResult(faithfulness=0.8, relevancy=0.8, completeness=0.8, failure_mode="chua-ro")

    assert verdict.failure_mode is FailureMode.NONE
    assert verdict.score == 0.8


def test_unknown_next_action_falls_back_to_regenerate():
    """Verdict không đọc được KHÔNG được trở thành lý do cho câu trả lời kém đi thẳng tới Sale."""
    verdict = VerifierResult(faithfulness=0.2, relevancy=0.2, next_action="???")

    assert verdict.next_action is NextAction.REGENERATE


def test_underscore_and_case_variants_are_accepted():
    verdict = VerifierResult(faithfulness=0.5, relevancy=0.5, failure_mode="Hallucinated_Fact")

    assert verdict.failure_mode is FailureMode.HALLUCINATED_FACT


def test_scores_on_a_0_100_scale_are_rescaled():
    assert VerifierResult(faithfulness=85, relevancy=90, completeness=80).score == pytest.approx(0.8)


def test_judge_failure_scores_zero_and_declines(judge, monkeypatch):
    """Verifier hỏng phải trượt kín, và phải nói rõ là hỏng chứ không giả vờ chấm điểm."""

    def _boom(prompt, schema, system_instruction=None):
        raise RuntimeError("Gemini down")

    monkeypatch.setattr(verifier_service, "generate_json", _boom)

    result = score_answer(QUERY, ANSWER, CONTEXT)

    assert result.score == 0.0
    assert result.next_action is NextAction.DECLINE
    assert result.feedback


def test_empty_context_cannot_be_called_faithful(judge):
    calls = judge(_verdict())

    result = score_answer(QUERY, ANSWER, [])

    assert result.score == 0.0
    assert calls == []


def test_unparseable_verdict_scores_zero(judge):
    judge(None)

    assert score_answer(QUERY, ANSWER, CONTEXT).score == 0.0
