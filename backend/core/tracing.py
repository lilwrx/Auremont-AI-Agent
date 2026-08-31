"""Per-run traces of the agent pipeline: every decision, tool call and retry.

The audit log (`backend/core/audit.py`) records *what happened to a user* — one row per
request, persisted to MySQL, kept for months. This module records *how the agent got
there* — a dozen steps per question, written to a JSONL file, kept for as long as the
eval flywheel needs them. Two different questions, so two different sinks: routing every
pipeline step through `log_event` would put roughly eight rows into `audit_logs` per
question and drown the business trail it exists to keep readable.

A trace answers the question a score cannot: *why*. `verifier_score=0.4` says an answer
was bad; the trace says retrieval returned two documents, the inventory tool was skipped,
the first draft was rejected as `incomplete-answer`, and the regeneration scored no
better. That is the difference between knowing a run failed and being able to fix it.

Traces are also the raw material for `eval/`: `scripts/build_eval_set.py` turns recorded
runs into graded cases, which is the "trace runs -> label failures -> build eval set"
half of the flywheel.

The JSONL export is disabled by default (`TRACING_ENABLED`). The Admin dashboard can
independently persist the same content-free records to MySQL with
`OBSERVABILITY_METRICS_ENABLED`. Both writes are best-effort and never raise: a full disk,
read-only mount or metrics outage must degrade observability, never answer a Sale's
question with a 500.
"""

import json
import logging
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.core.config import settings

logger = logging.getLogger(__name__)

_write_lock = threading.Lock()

_current_run: ContextVar["TraceRun | None"] = ContextVar("current_trace_run", default=None)


@dataclass
class TraceStep:
    """One step of a run: a decision taken, a tool called, or a retry started."""

    name: str
    at_ms: float
    fields: dict[str, Any] = field(default_factory=dict)


@dataclass
class TraceRun:
    """Everything one question did, from cache check to final answer."""

    run_id: str
    query_len: int
    project_id: str | None
    clearance: str
    started_at: str
    started_perf: float
    steps: list[TraceStep] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)

    def step(self, name: str, **fields: Any) -> None:
        self.steps.append(
            TraceStep(
                name=name,
                at_ms=round((time.perf_counter() - self.started_perf) * 1000, 2),
                fields=fields,
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "duration_ms": round((time.perf_counter() - self.started_perf) * 1000, 2),
            "query_len": self.query_len,
            "project_id": self.project_id,
            "clearance": self.clearance,
            "steps": [{"name": s.name, "at_ms": s.at_ms, **s.fields} for s in self.steps],
            **self.outcome,
        }


def start_run(*, query_len: int, project_id: str | None, clearance: str) -> TraceRun | None:
    """Begin tracing one question when either trace sink is enabled.

    ``TRACING_ENABLED`` controls the optional JSONL eval/debug export. The Admin
    dashboard uses the durable MySQL sink controlled by
    ``OBSERVABILITY_METRICS_ENABLED``; the two can be enabled independently.
    """
    if not settings.tracing_enabled and not settings.observability_metrics_enabled:
        return None

    run = TraceRun(
        run_id=uuid.uuid4().hex[:16],
        query_len=query_len,
        project_id=project_id,
        clearance=clearance,
        started_at=datetime.now(UTC).isoformat(),
        started_perf=time.perf_counter(),
    )
    _current_run.set(run)
    return run


def step(name: str, **fields: Any) -> None:
    """Record one step against the run in progress; a no-op when tracing is off.

    Called from pipeline nodes, which must stay usable outside a traced run (unit tests
    drive them directly), so a missing run is normal rather than an error.
    """
    run = _current_run.get()
    if run is not None:
        run.step(name, **fields)


def current_run_id() -> str | None:
    """Return the active trace id so provider usage can be joined to its pipeline."""

    run = _current_run.get()
    return run.run_id if run is not None else None


def set_outcome(**outcome: Any) -> None:
    """Record how the run ended, without closing it.

    Split from `finish` so the caller can report the outcome at each of its several exit
    points while still closing the run exactly once, in a `finally`.
    """
    run = _current_run.get()
    if run is not None:
        run.outcome.update(outcome)


def finish(**outcome: Any) -> None:
    """Close a run and flush it to every enabled sink, best-effort."""
    run = _current_run.get()
    if run is None:
        return

    _current_run.set(None)
    run.outcome.update(outcome)

    record = run.as_dict()

    if settings.observability_metrics_enabled:
        try:
            from backend.core.observability_sink import persist_trace_run

            persist_trace_run(record)
        except Exception:  # pragma: no cover - observability must never break a request
            logger.warning(
                "Could not persist the pipeline trace.",
                exc_info=True,
                extra={"event": "tracing.persist.failed", "run_id": run.run_id},
            )

    if settings.tracing_enabled:
        try:
            _append(record)
        except Exception:  # pragma: no cover - observability must never break a request
            logger.warning(
                "Could not write the pipeline trace.",
                exc_info=True,
                extra={"event": "tracing.write.failed", "run_id": run.run_id},
            )


def _append(record: dict[str, Any]) -> None:
    path = Path(settings.trace_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(record, ensure_ascii=False, default=str)
    with _write_lock, path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def read_runs(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Read back recorded runs, skipping any line that is not valid JSON.

    A truncated final line is normal — the file is appended to by a running server — so a
    reader that refused to parse the rest because of it would be useless in practice.
    """
    target = Path(path or settings.trace_file)
    if not target.exists():
        return []

    runs = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            runs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return runs
