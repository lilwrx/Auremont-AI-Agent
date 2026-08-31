"""Regression gate: run every case in `eval/golden_dataset.py` through the real pipeline.

Unlike the trace-based graders in `eval/graders.py` — which can only judge traffic that
already happened — this runs a fixed, hand-picked set of Sale questions on every test run,
so a routing or prompt-assembly regression is caught on the PR that introduces it rather
than after it reaches production traffic.

Retrieval, inventory, and the LLM call are stubbed per case at the same boundary
`test_tracing.py` and `test_agent_pipeline_reflexion.py` stub at — deterministic, no network,
no API key required. What's under test is the pipeline's own wiring (does a live-inventory
question call the tool? does a price figure trigger HITL? does zero evidence decline instead
of hallucinating?), not the quality of Gemini's prose.
"""

import pytest

from backend.services import agent_pipeline
from backend.services.inventory_service import InventoryApiError
from backend.services.verifier_service import FailureMode, NextAction, VerifierResult
from eval.golden_dataset import GOLDEN_CASES, GoldenCase


def _stub(monkeypatch, case: GoldenCase) -> None:
    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *a, **k: case.retrieved_docs)
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "_store_cache", lambda *a, **k: None)

    def _lookup(project_id, query):
        if case.inventory_raises:
            raise InventoryApiError("down")
        return case.inventory_units

    monkeypatch.setattr(agent_pipeline, "lookup_inventory", _lookup)

    def _generate_json(prompt, schema, **_kwargs):
        return schema(
            text=case.answer_text,
            quick_replies=list(case.quick_replies),
            suggested_questions=list(case.suggested_questions),
        )

    monkeypatch.setattr(agent_pipeline, "generate_json", _generate_json)

    verdict = VerifierResult(
        faithfulness=case.verifier_score,
        relevancy=case.verifier_score,
        completeness=case.verifier_score,
        failure_mode=FailureMode(case.verifier_failure_mode),
        feedback="",
        next_action=NextAction(case.verifier_next_action),
    )
    monkeypatch.setattr(agent_pipeline.verifier_service, "score_answer", lambda *a, **k: verdict)


@pytest.mark.parametrize("case", GOLDEN_CASES, ids=[c.case_id for c in GOLDEN_CASES])
def test_golden_case(monkeypatch, case: GoldenCase):
    _stub(monkeypatch, case)

    result = agent_pipeline.run_pipeline(case.query, project_id=case.project_id)

    if case.expect_notice:
        assert result.citations == []
        assert result.verifier_score == 0.0
    else:
        cited_ids = {c["document_id"] for c in result.citations}
        assert cited_ids == case.expect_cited_document_ids, (
            f"{case.case_id}: expected citations {case.expect_cited_document_ids}, got {cited_ids}"
        )
        assert result.requires_hitl == case.expect_requires_hitl, (
            f"{case.case_id}: expected requires_hitl={case.expect_requires_hitl}, got {result.requires_hitl}"
        )

    for phrase in case.expect_answer_contains:
        assert phrase in result.draft_answer, (
            f"{case.case_id}: expected {phrase!r} in answer, got {result.draft_answer!r}"
        )


def test_every_answering_case_carries_a_reference_answer():
    """`eval/deepeval_suite.py` grades the real model against `expected_output` instead of
    against a judge's opinion, so a case added without one silently loses that gate — and
    the suite itself is not run in CI to notice. Cases that never reach Generate have no
    model-written answer to compare, so they are exempt.

    The facts the answer must contain live in `expect_answer_contains`; a reference answer
    that commits to none of them cannot fail a wrong draft.
    """
    for case in GOLDEN_CASES:
        if case.expect_notice:
            continue

        assert case.expected_output, f"{case.case_id}: no reference answer"
        assert case.expect_answer_contains, f"{case.case_id}: no required facts"


@pytest.mark.parametrize("case", [c for c in GOLDEN_CASES if c.expect_inventory_called], ids=lambda c: c.case_id)
def test_golden_case_calls_inventory(monkeypatch, case: GoldenCase):
    """A subset of cases must prove the inventory tool actually ran, not just that the
    final answer happens to mention a unit code — the live-inventory bug class this guards
    against is silently answering stock questions out of stale documents instead."""
    called: list[str | None] = []
    _stub(monkeypatch, case)

    real_lookup = agent_pipeline.lookup_inventory

    def _tracking_lookup(project_id, query):
        called.append(project_id)
        return real_lookup(project_id, query)

    monkeypatch.setattr(agent_pipeline, "lookup_inventory", _tracking_lookup)

    agent_pipeline.run_pipeline(case.query, project_id=case.project_id)

    assert called, f"{case.case_id}: expected the inventory tool to be called"
