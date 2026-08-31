"""Best-effort MySQL persistence for operational AI metrics.

Metrics use their own short transaction. A broken metrics table or database connection
must never roll back a document upload or turn a valid chatbot answer into HTTP 500.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Any

from backend.core.context import get_request_id
from backend.core.mysql_client import SessionLocal
from backend.models.observability import LlmUsageEvent, PipelineTraceRun

logger = logging.getLogger(__name__)


def persist_trace_run(record: dict[str, Any]) -> None:
    """Persist one completed pipeline trace without propagating failures."""

    started_at = _parse_datetime(record.get("started_at"))
    run_id = record.get("run_id")
    if started_at is None or not isinstance(run_id, str) or not run_id:
        return

    safe_record = _json_safe(record)
    _persist(
        PipelineTraceRun(
            run_id=run_id,
            started_at=started_at,
            duration_ms=_as_float(record.get("duration_ms")) or 0.0,
            project_id=_as_optional_str(record.get("project_id"), 36),
            clearance=_as_optional_str(record.get("clearance"), 20) or "unknown",
            outcome=_as_optional_str(record.get("outcome"), 32) or "completed",
            verifier_score=_as_float(record.get("verifier_score")),
            payload=safe_record,
        ),
        failed_event="observability.trace.persist.failed",
    )


def persist_llm_usage(
    *,
    usage_id: str,
    run_id: str | None,
    operation: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
) -> None:
    """Persist provider usage for one successful response without prompt content."""

    _persist(
        LlmUsageEvent(
            usage_id=usage_id[:32],
            run_id=run_id[:32] if run_id else None,
            request_id=(get_request_id() or None),
            operation=(operation or "gemini_generation")[:64],
            model=model[:100],
            input_tokens=max(int(input_tokens), 0),
            output_tokens=max(int(output_tokens), 0),
            total_tokens=max(int(total_tokens), 0),
        ),
        failed_event="observability.usage.persist.failed",
    )


def _persist(row: object, *, failed_event: str) -> None:
    session = None
    try:
        session = SessionLocal()
        session.add(row)
        session.commit()
    except Exception:
        logger.warning(
            "Could not persist observability metric to MySQL.",
            exc_info=True,
            extra={"event": failed_event},
        )
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.warning(
                    "Could not close observability persistence session",
                    exc_info=True,
                    extra={"event": "observability.session.close.failed"},
                )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _json_safe(value: dict[str, Any]) -> dict[str, Any]:
    """Round-trip through JSON so an enum/custom scalar cannot poison the INSERT."""

    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _as_optional_str(value: object, limit: int) -> str | None:
    return str(value)[:limit] if value is not None else None


def _as_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)
