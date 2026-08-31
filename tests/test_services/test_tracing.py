"""Pipeline tracing: every decision, tool call and retry recorded for one run.

These tests are about what a trace has to contain to be worth keeping. A trace that
records only the final answer is what the system already had (the audit log) and answers
nothing new — the value is entirely in the intermediate steps, so that is what is
asserted here.
"""

import json

import pytest

from backend.core import tracing
from backend.core.config import settings
from backend.services import agent_pipeline
from backend.services.verifier_service import FailureMode, NextAction, VerifierResult

QUERY = "Gia can 2PN va con bao nhieu can?"
DOCS = [{"document_id": 1, "title": "bang-gia.pdf", "page": 2, "content": "Can 2PN tu 3,6 ty.", "score": 0.82}]


@pytest.fixture
def trace_file(tmp_path, monkeypatch):
    """Bat tracing va ghi vao file tam, tra ve ham doc lai cac run."""
    path = tmp_path / "runs.jsonl"
    monkeypatch.setattr(settings, "tracing_enabled", True)
    monkeypatch.setattr(settings, "trace_file", str(path))
    return lambda: tracing.read_runs(path)


def _verdict(score: float, **overrides) -> VerifierResult:
    base = {
        "faithfulness": score,
        "relevancy": score,
        "completeness": score,
        "failure_mode": FailureMode.NONE if score >= 0.7 else FailureMode.INCOMPLETE_ANSWER,
        "feedback": "" if score >= 0.7 else "Chua tra loi ton kho.",
        "next_action": NextAction.ACCEPT if score >= 0.7 else NextAction.REGENERATE,
    }
    return VerifierResult(**(base | overrides))


def _stub_pipeline(monkeypatch, *, verdicts, needs_inventory=False, units=None, inventory_fails=False):
    remaining = list(verdicts)

    monkeypatch.setattr(agent_pipeline, "retrieve", lambda *a, **k: DOCS)
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "_store_cache", lambda *a, **k: None)
    monkeypatch.setattr(agent_pipeline, "query_needs_inventory", lambda query: needs_inventory)
    monkeypatch.setattr(agent_pipeline, "query_needs_documents", lambda query: True)
    monkeypatch.setattr(agent_pipeline.risk_service, "detect_commitment_risk", lambda answer: False)
    monkeypatch.setattr(agent_pipeline, "generate_json", lambda _p, schema, **k: schema(text="- Can 2PN tu 3,6 ty."))
    monkeypatch.setattr(
        agent_pipeline.verifier_service,
        "score_answer",
        lambda *a, **k: remaining.pop(0) if remaining else _verdict(0.9),
    )

    if needs_inventory:

        def _lookup(project_id, query):
            if inventory_fails:
                raise agent_pipeline.InventoryApiError("down")
            return units or []

        monkeypatch.setattr(agent_pipeline, "lookup_inventory", _lookup)


def _steps(run: dict, name: str) -> list[dict]:
    return [step for step in run["steps"] if step["name"] == name]


def test_a_run_is_recorded_with_its_steps(trace_file, monkeypatch):
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.9)])

    agent_pipeline.run_pipeline(QUERY)

    runs = trace_file()
    assert len(runs) == 1
    assert runs[0]["outcome"] == "answered"
    assert runs[0]["steps"]


def test_tracing_disabled_writes_nothing(tmp_path, monkeypatch):
    path = tmp_path / "runs.jsonl"
    monkeypatch.setattr(settings, "tracing_enabled", False)
    monkeypatch.setattr(settings, "trace_file", str(path))
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.9)])

    agent_pipeline.run_pipeline(QUERY)

    assert not path.exists()


def test_mysql_metrics_can_run_without_jsonl_tracing(tmp_path, monkeypatch):
    path = tmp_path / "runs.jsonl"
    persisted: list[dict] = []
    monkeypatch.setattr(settings, "tracing_enabled", False)
    monkeypatch.setattr(settings, "observability_metrics_enabled", True)
    monkeypatch.setattr(settings, "trace_file", str(path))
    monkeypatch.setattr("backend.core.observability_sink.persist_trace_run", persisted.append)
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.9)])

    agent_pipeline.run_pipeline(QUERY)

    assert not path.exists()
    assert len(persisted) == 1
    assert persisted[0]["outcome"] == "answered"
    assert persisted[0]["steps"]


def test_routing_decisions_are_recorded(trace_file, monkeypatch):
    """Vi sao cau hoi nay khong goi API ton kho — chi tra loi duoc neu co ghi lai."""
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.9)])

    agent_pipeline.run_pipeline(QUERY)

    intent = _steps(trace_file()[0], "intent")[0]
    assert intent["needs_inventory"] is False
    assert intent["needs_document_retrieval"] is True


def test_retrieval_records_what_came_back(trace_file, monkeypatch):
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.9)])

    agent_pipeline.run_pipeline(QUERY)

    retrieve = _steps(trace_file()[0], "retrieve")[0]
    assert retrieve["doc_count"] == 1
    assert retrieve["top_score"] == 0.82
    assert retrieve["document_ids"] == [1]


def test_tool_call_records_result_and_latency(trace_file, monkeypatch):
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.9)], needs_inventory=True, units=[])

    agent_pipeline.run_pipeline(QUERY)

    tool = _steps(trace_file()[0], "tool.inventory")[0]
    assert tool["ok"] is True
    assert tool["unit_count"] == 0
    assert "duration_ms" in tool


def test_failed_tool_call_is_still_traced_with_latency(trace_file, monkeypatch):
    """Timeout va tu choi ngay lap tuc la hai loi khac nhau, chi do tre phan biet duoc."""
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.9)], needs_inventory=True, inventory_fails=True)

    agent_pipeline.run_pipeline(QUERY)

    tool = _steps(trace_file()[0], "tool.inventory")[0]
    assert tool["ok"] is False
    assert "duration_ms" in tool


def test_retry_is_visible_as_a_second_attempt(trace_file, monkeypatch):
    """Retry va Reflexion khac nhau o cho lan 2 co mang theo correction hay khong."""
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.3), _verdict(0.9)])

    agent_pipeline.run_pipeline(QUERY)

    generates = _steps(trace_file()[0], "generate")
    assert [g["attempt"] for g in generates] == [1, 2]
    assert generates[0]["corrected"] is False
    assert generates[1]["corrected"] is True


def test_failure_mode_is_recorded_on_every_verify(trace_file, monkeypatch):
    """Nhan de build eval set — day la buoc 'Label failures' cua flywheel."""
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.3), _verdict(0.9)])

    agent_pipeline.run_pipeline(QUERY)

    verifies = _steps(trace_file()[0], "verify")
    assert verifies[0]["failure_mode"] == FailureMode.INCOMPLETE_ANSWER.value
    assert verifies[1]["failure_mode"] == FailureMode.NONE.value


def test_route_after_verify_records_the_decision(trace_file, monkeypatch):
    _stub_pipeline(
        monkeypatch,
        verdicts=[_verdict(0.2, failure_mode=FailureMode.MISSING_EVIDENCE, next_action=NextAction.DECLINE)],
    )

    agent_pipeline.run_pipeline(QUERY)

    route = _steps(trace_file()[0], "route.after_verify")[0]
    assert route["decision"] == "decline"
    assert route["reason"] == "verifier_declined"


def test_answer_text_never_reaches_the_trace(trace_file, monkeypatch):
    """Trace ghi ra file, khong duoc mang theo noi dung tra loi khach hang."""
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.3), _verdict(0.9)])

    agent_pipeline.run_pipeline(QUERY)

    raw = json.dumps(trace_file()[0], ensure_ascii=False)
    assert "3,6 ty" not in raw
    assert "Chua tra loi ton kho" not in raw


def test_a_write_failure_does_not_break_the_answer(tmp_path, monkeypatch):
    """Het dia hay mount chi doc thi mat quan sat, khong duoc mat cau tra loi."""
    monkeypatch.setattr(settings, "tracing_enabled", True)
    monkeypatch.setattr(settings, "trace_file", str(tmp_path))
    _stub_pipeline(monkeypatch, verdicts=[_verdict(0.9)])

    result = agent_pipeline.run_pipeline(QUERY)

    assert result.draft_answer


def test_read_runs_skips_a_corrupt_line(tmp_path, monkeypatch):
    """File dang duoc ghi vao thi dong cuoi co the dut — khong duoc vi the ma bo ca file."""
    path = tmp_path / "runs.jsonl"
    path.write_text('{"run_id": "a"}\nnot-json\n{"run_id": "b"}\n', encoding="utf-8")

    assert [run["run_id"] for run in tracing.read_runs(path)] == ["a", "b"]
