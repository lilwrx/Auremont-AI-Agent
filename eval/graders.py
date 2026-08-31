"""Automatic graders over recorded pipeline runs.

The eval flywheel is: trace runs -> label failures -> build an eval set -> run graders ->
fix prompt/tool/state -> re-test. This module is the "run graders" step. It reads runs
recorded by `backend/core/tracing.py` and turns them into a pass/fail report with a
breakdown by failure mode, so a change to a prompt or a retrieval setting can be measured
against the previous run instead of argued about.

Graders here are deliberately *deterministic* and read only trace fields — no LLM call, no
network. An LLM-as-judge already ran inside the pipeline (`verifier_service`) and its
verdict is one of the recorded fields; grading that recording a second time with another
model would add cost and variance while measuring roughly the same thing. What these
graders check instead are the properties that must hold regardless of what any model
thinks: that the agent grounded its answer, that it did not silently skip a tool it
needed, that retries actually carried a correction, and that latency stayed inside budget.
"""

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

LATENCY_BUDGET_MS = 3000.0


@dataclass
class GradeResult:
    """One grader's verdict on one run."""

    grader: str
    passed: bool
    detail: str = ""


@dataclass
class RunGrade:
    run_id: str
    grades: list[GradeResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(grade.passed for grade in self.grades)

    @property
    def failures(self) -> list[GradeResult]:
        return [grade for grade in self.grades if not grade.passed]


def _steps(run: dict[str, Any], name: str) -> list[dict[str, Any]]:
    return [step for step in run.get("steps") or [] if step.get("name") == name]


def grade_answered_runs_are_grounded(run: dict[str, Any]) -> GradeResult:
    """An answer served to a Sale must cite something.

    A run that answered with zero citations either bypassed retrieval or generated from
    the model's own knowledge — both are exactly the failure this system exists to
    prevent, and neither shows up in the Verifier score.
    """
    name = "answered_runs_are_grounded"
    if run.get("outcome") != "answered" or run.get("used_cache"):
        return GradeResult(name, True)

    citations = run.get("citation_count", 0)
    if citations > 0:
        return GradeResult(name, True)

    return GradeResult(name, False, "Answered with no citations.")


def grade_retrieval_ran_when_needed(run: dict[str, Any]) -> GradeResult:
    """A question routed to document retrieval must actually have retrieved."""
    name = "retrieval_ran_when_needed"
    intent = _steps(run, "intent")
    if not intent or not intent[0].get("needs_document_retrieval"):
        return GradeResult(name, True)

    if _steps(run, "retrieve"):
        return GradeResult(name, True)

    return GradeResult(name, False, "Intent asked for retrieval but no retrieve step ran.")


def grade_inventory_tool_called_when_needed(run: dict[str, Any]) -> GradeResult:
    """Live stock questions must hit the inventory API, never answer from documents.

    Documents hold last month's availability. Answering a stock question out of them is
    wrong in a way that reads perfectly fluent, which is why this is checked structurally
    rather than left to a judge.
    """
    name = "inventory_tool_called_when_needed"
    intent = _steps(run, "intent")
    if not intent or not intent[0].get("needs_inventory"):
        return GradeResult(name, True)

    if _steps(run, "tool.inventory"):
        return GradeResult(name, True)

    return GradeResult(name, False, "Inventory was needed but the tool never ran.")


def grade_retries_carry_a_correction(run: dict[str, Any]) -> GradeResult:
    """A second attempt must be a Reflexion, not a blind repeat.

    This is the grader that would have caught the pre-Reflexion behaviour: a retry that
    re-runs an identical prompt usually reproduces the same answer and burns a model call
    to do it.
    """
    name = "retries_carry_a_correction"
    generates = _steps(run, "generate")
    blind = [step for step in generates if step.get("attempt", 1) > 1 and not step.get("corrected")]

    if not blind:
        return GradeResult(name, True)

    return GradeResult(name, False, f"{len(blind)} retry attempt(s) carried no correction.")


def grade_latency_within_budget(run: dict[str, Any]) -> GradeResult:
    """Under the field response budget, measured end to end."""
    name = "latency_within_budget"
    duration = run.get("duration_ms")
    if not isinstance(duration, int | float) or duration <= LATENCY_BUDGET_MS:
        return GradeResult(name, True)

    return GradeResult(name, False, f"{duration:.0f}ms over the {LATENCY_BUDGET_MS:.0f}ms budget.")


GRADERS = (
    grade_answered_runs_are_grounded,
    grade_retrieval_ran_when_needed,
    grade_inventory_tool_called_when_needed,
    grade_retries_carry_a_correction,
    grade_latency_within_budget,
)


def grade_run(run: dict[str, Any]) -> RunGrade:
    return RunGrade(run_id=run.get("run_id", "?"), grades=[grader(run) for grader in GRADERS])


def build_report(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate graded runs into the report the flywheel is steered by.

    `failure_modes` is the breakdown that decides what to fix next: twenty runs failing as
    `missing-evidence` means the corpus has a hole, while twenty `hallucinated-fact` means
    the prompt or the grounding constraints need work. A single pass rate cannot tell
    those apart, which is why it is not the only number reported.
    """
    graded = [grade_run(run) for run in runs]

    per_grader: dict[str, dict[str, Any]] = {}
    for grader_name in dict.fromkeys(grade.grader for run_grade in graded for grade in run_grade.grades):
        results = [grade for run_grade in graded for grade in run_grade.grades if grade.grader == grader_name]
        failed = [grade for grade in results if not grade.passed]
        per_grader[grader_name] = {
            "total": len(results),
            "passed": len(results) - len(failed),
            "failed": len(failed),
            "examples": [grade.detail for grade in failed[:3]],
        }

    failure_modes = Counter(
        run.get("failure_mode") for run in runs if run.get("failure_mode") and run.get("failure_mode") != "none"
    )
    outcomes = Counter(run.get("outcome") for run in runs)
    latencies = sorted(run["duration_ms"] for run in runs if isinstance(run.get("duration_ms"), int | float))

    return {
        "runs": len(runs),
        "passed": sum(1 for run_grade in graded if run_grade.passed),
        "failed": sum(1 for run_grade in graded if not run_grade.passed),
        "pass_rate": round(sum(1 for g in graded if g.passed) / len(graded), 4) if graded else 0.0,
        "outcomes": dict(outcomes),
        "failure_modes": dict(failure_modes),
        "graders": per_grader,
        "latency_ms": {
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
            "max": latencies[-1] if latencies else None,
        },
        "retries": sum(1 for run in runs if run.get("retry_count")),
    }


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    """Nearest-rank percentile; None for an empty sample.

    Nearest-rank rather than interpolating: these samples are small enough that an
    interpolated p95 would mostly be an artefact of the interpolation.
    """
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, int(round(fraction * (len(sorted_values) - 1))))
    return round(sorted_values[index], 2)
