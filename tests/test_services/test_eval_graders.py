"""Graders over recorded runs, and the report they aggregate into.

Each grader is tested from both sides — a run it must pass and a run it must fail —
because a grader that never fails is indistinguishable from one that is not wired up, and
that is exactly the bug the report breakdown had.
"""

from eval.graders import (
    build_report,
    grade_answered_runs_are_grounded,
    grade_inventory_tool_called_when_needed,
    grade_latency_within_budget,
    grade_retries_carry_a_correction,
    grade_retrieval_ran_when_needed,
)


def _run(**overrides) -> dict:
    base = {
        "run_id": "r1",
        "outcome": "answered",
        "citation_count": 2,
        "used_cache": False,
        "duration_ms": 800.0,
        "steps": [],
    }
    return base | overrides


def test_answered_run_without_citations_fails():
    assert not grade_answered_runs_are_grounded(_run(citation_count=0)).passed


def test_answered_run_with_citations_passes():
    assert grade_answered_runs_are_grounded(_run(citation_count=1)).passed


def test_cache_hit_is_not_judged_on_citations():
    """Cau tra loi tu cache da qua bar nay mot lan roi khi duoc ghi vao cache."""
    assert grade_answered_runs_are_grounded(_run(citation_count=0, used_cache=True)).passed


def test_declined_run_is_not_judged_on_citations():
    assert grade_answered_runs_are_grounded(_run(outcome="notice", citation_count=0)).passed


def test_missing_retrieval_when_intent_asked_for_it_fails():
    run = _run(steps=[{"name": "intent", "needs_document_retrieval": True}])

    assert not grade_retrieval_ran_when_needed(run).passed


def test_retrieval_present_passes():
    run = _run(steps=[{"name": "intent", "needs_document_retrieval": True}, {"name": "retrieve"}])

    assert grade_retrieval_ran_when_needed(run).passed


def test_inventory_needed_but_never_called_fails():
    """Tra loi ton kho tu tai lieu la sai kieu doc len van rat troi chay."""
    run = _run(steps=[{"name": "intent", "needs_inventory": True}])

    assert not grade_inventory_tool_called_when_needed(run).passed


def test_inventory_not_needed_passes_without_the_tool():
    run = _run(steps=[{"name": "intent", "needs_inventory": False}])

    assert grade_inventory_tool_called_when_needed(run).passed


def test_blind_retry_fails():
    """Chinh la hanh vi truoc khi co Reflexion — grader nay phai bat duoc."""
    run = _run(
        steps=[
            {"name": "generate", "attempt": 1, "corrected": False},
            {"name": "generate", "attempt": 2, "corrected": False},
        ]
    )

    assert not grade_retries_carry_a_correction(run).passed


def test_corrected_retry_passes():
    run = _run(
        steps=[
            {"name": "generate", "attempt": 1, "corrected": False},
            {"name": "generate", "attempt": 2, "corrected": True},
        ]
    )

    assert grade_retries_carry_a_correction(run).passed


def test_latency_over_budget_fails():
    assert not grade_latency_within_budget(_run(duration_ms=5200.0)).passed


def test_latency_within_budget_passes():
    assert grade_latency_within_budget(_run(duration_ms=2900.0)).passed


def test_report_counts_every_grader_against_every_run():
    """Breakdown tung bao 0/0 cho moi grader trong khi pass rate van dung — bug that."""
    report = build_report([_run(), _run(run_id="r2")])

    assert report["runs"] == 2
    for stats in report["graders"].values():
        assert stats["total"] == 2


def test_report_breaks_failures_down_by_mode():
    """Con so quyet dinh sua gi tiep theo: thieu tai lieu hay prompt kem la hai viec khac nhau."""
    runs = [
        _run(failure_mode="missing-evidence"),
        _run(run_id="r2", failure_mode="missing-evidence"),
        _run(run_id="r3", failure_mode="hallucinated-fact"),
        _run(run_id="r4", failure_mode="none"),
    ]

    report = build_report(runs)

    assert report["failure_modes"] == {"missing-evidence": 2, "hallucinated-fact": 1}


def test_report_pass_rate_reflects_a_failing_run():
    report = build_report([_run(), _run(run_id="r2", citation_count=0)])

    assert report["passed"] == 1
    assert report["failed"] == 1
    assert report["pass_rate"] == 0.5


def test_report_on_no_runs_does_not_divide_by_zero():
    report = build_report([])

    assert report["runs"] == 0
    assert report["pass_rate"] == 0.0
