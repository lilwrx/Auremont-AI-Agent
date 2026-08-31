"""The Reflexion loop: a rejected draft is regenerated *with* the reason it was rejected.

The point of these tests is the difference between a retry and a Reflexion. A retry
re-runs an identical prompt and tends to reproduce the same answer; a Reflexion carries
the Verifier's specific complaint back into the next attempt. What makes that real is
`verifier_feedback` reaching the second Generate prompt — the assertion in
`test_rejection_reason_reaches_the_regeneration_prompt` is the one that matters most here.
"""

from backend.ai import prompts
from backend.services import agent_pipeline
from backend.services.verifier_service import FailureMode, NextAction, VerifierResult

QUERY = "Gia can 2PN va tien do thanh toan the nao?"
DOCS = [{"document_id": 1, "title": "bang-gia.pdf", "page": 2, "content": "Can 2PN tu 3,6 ty dong."}]
COMPLAINT = "Moi tra loi gia, chua tra loi tien do thanh toan."


def _verdict(score: float, **overrides) -> VerifierResult:
    base = {
        "faithfulness": score,
        "relevancy": score,
        "completeness": score,
        "failure_mode": FailureMode.NONE if score >= 0.7 else FailureMode.INCOMPLETE_ANSWER,
        "feedback": "" if score >= 0.7 else COMPLAINT,
        "next_action": NextAction.ACCEPT if score >= 0.7 else NextAction.REGENERATE,
    }
    return VerifierResult(**(base | overrides))


def _run(monkeypatch, *, verdicts: list[VerifierResult]) -> list[str]:
    """Drive the pipeline with a scripted sequence of verdicts; return the prompts sent.

    Retrieval, inventory and the cache are all stubbed out so the only thing under test is
    the Generate/Verify/regenerate cycle.
    """
    prompts_seen: list[str] = []
    remaining = list(verdicts)

    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *a, **k: DOCS)
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "_store_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "query_needs_inventory", lambda query: False)
    monkeypatch.setattr(agent_pipeline.risk_service, "detect_commitment_risk", lambda answer: False)

    def _generate_json(prompt, schema, system_instruction=None):
        prompts_seen.append(prompt)
        return schema(text="- Can 2PN tu 3,6 ty dong.")

    monkeypatch.setattr(agent_pipeline, "generate_json", _generate_json)
    monkeypatch.setattr(
        agent_pipeline.verifier_service,
        "score_answer",
        lambda *a, **k: remaining.pop(0) if remaining else _verdict(0.9),
    )

    agent_pipeline.run_pipeline(QUERY)
    return prompts_seen


def test_rejection_reason_reaches_the_regeneration_prompt(monkeypatch):
    """Lan sinh lai phai duoc biet lan truoc sai o dau — day la diem cot loi cua Reflexion."""
    seen = _run(monkeypatch, verdicts=[_verdict(0.3), _verdict(0.9)])

    assert len(seen) == 2
    assert COMPLAINT not in seen[0]
    assert COMPLAINT in seen[1]
    assert "SỬA LỖI CỦA LẦN TRẢ LỜI TRƯỚC" in seen[1]


def test_first_attempt_carries_no_correction_block(monkeypatch):
    """Chua co gi de sua thi prompt phai y het truoc khi co Reflexion."""
    seen = _run(monkeypatch, verdicts=[_verdict(0.9)])

    assert len(seen) == 1
    assert "SỬA LỖI CỦA LẦN TRẢ LỜI TRƯỚC" not in seen[0]


def test_correction_block_still_forbids_inventing_data(monkeypatch):
    """Suc ep phai sua khong duoc tro thanh suc ep bia them cho du y."""
    seen = _run(monkeypatch, verdicts=[_verdict(0.3), _verdict(0.9)])

    assert "chưa có dữ liệu" in seen[1]


def test_decline_skips_the_retry_entirely(monkeypatch):
    """Ngu canh khong he co du lieu thi sinh lai cung vo ich — dung tieu them mot lan goi LLM."""
    seen = _run(
        monkeypatch,
        verdicts=[_verdict(0.2, failure_mode=FailureMode.MISSING_EVIDENCE, next_action=NextAction.DECLINE)],
    )

    assert len(seen) == 1


def test_passing_score_overrides_a_contradictory_decline(monkeypatch):
    """Judge cham diem dat roi lai doi tu choi la tu mau thuan — diem so thang."""
    seen = _run(monkeypatch, verdicts=[_verdict(0.9, next_action=NextAction.DECLINE)])

    assert len(seen) == 1


def test_all_three_scores_travel_out_of_the_pipeline(monkeypatch):
    """Admin Tab 2 chart ba tieu chi rieng, nen ca ba phai ra duoc toi router."""
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *a, **k: DOCS)
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "_store_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "query_needs_inventory", lambda query: False)
    monkeypatch.setattr(agent_pipeline.risk_service, "detect_commitment_risk", lambda answer: False)
    monkeypatch.setattr(
        agent_pipeline, "generate_json", lambda _p, schema, **k: schema(text="- Can 2PN tu 3,6 ty dong.")
    )
    monkeypatch.setattr(
        agent_pipeline.verifier_service,
        "score_answer",
        lambda *a, **k: _verdict(0.95, completeness=0.8),
    )

    result = agent_pipeline.run_pipeline(QUERY)

    assert result.faithfulness == 0.95
    assert result.answer_relevancy == 0.95
    assert result.completeness == 0.8
    assert result.verifier_score == 0.8


def test_incomplete_answer_is_blocked_even_when_grounded(monkeypatch):
    """Bam sat ngu canh nhung thieu y van phai bi chan — gia tri cua tieu chi completeness."""
    seen = _run(
        monkeypatch,
        verdicts=[
            _verdict(0.95, completeness=0.3, failure_mode=FailureMode.INCOMPLETE_ANSWER),
            _verdict(0.95, completeness=0.3, failure_mode=FailureMode.INCOMPLETE_ANSWER),
        ],
    )
    assert len(seen) == 2


def test_declined_answer_still_reports_why(monkeypatch):
    """Cau tra loi bi tu choi la ca Admin can chan doan nhat — khong duoc mat ly do."""
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *a, **k: DOCS)
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "_store_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "query_needs_inventory", lambda query: False)
    monkeypatch.setattr(agent_pipeline.risk_service, "detect_commitment_risk", lambda answer: False)
    monkeypatch.setattr(
        agent_pipeline, "generate_json", lambda _p, schema, **k: schema(text="- Can 2PN tu 3,6 ty dong.")
    )
    monkeypatch.setattr(
        agent_pipeline.verifier_service,
        "score_answer",
        lambda *a, **k: _verdict(
            0.1,
            failure_mode=FailureMode.MISSING_EVIDENCE,
            feedback="Ngu canh khong co tien do thanh toan.",
            next_action=NextAction.DECLINE,
        ),
    )

    result = agent_pipeline.run_pipeline(QUERY)

    assert result.failure_mode == FailureMode.MISSING_EVIDENCE.value
    assert result.verifier_feedback


def test_correction_is_the_last_block_in_the_prompt():
    """Chi thi sua loi phai la thu cuoi cung model doc truoc khi viet."""
    prompt = prompts.build_prompt(QUERY, DOCS, [], False, False, correction=COMPLAINT)

    assert prompt.rstrip().index(COMPLAINT) > prompt.index("NGỮ CẢNH TỪ TÀI LIỆU DỰ ÁN")


def test_blank_correction_leaves_the_prompt_untouched():
    without = prompts.build_prompt(QUERY, DOCS, [], False, False)
    with_blank = prompts.build_prompt(QUERY, DOCS, [], False, False, correction="   ")

    assert without == with_blank
