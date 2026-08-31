import re
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.deps import require_role
from backend.core.enums import MessageSender, SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.core.tracing import read_runs
from backend.models.audit_log import AuditLog
from backend.models.chat_session import ChatSession
from backend.models.message import Message
from backend.models.observability import LlmUsageEvent, PipelineTraceRun
from backend.models.project import Project
from backend.schemas.admin_dashboard import (
    AuditLogEntry,
    FallbackAlertResponse,
    IntentBucketMetric,
    ModuleUsageMetric,
    ObservabilityOverviewResponse,
    PopularProjectMetric,
    TokenDailyMetric,
    TokenMonitoringMetric,
    ToolReliabilityMetric,
    TraceStepResponse,
    TraceSummaryResponse,
    UserMonitoringMetric,
)
from backend.utils.time import utcnow
from backend.utils.vnd import BUDGET_UNIT_ALTERNATION, Profile, parse_vnd

router = APIRouter(
    prefix="/admin/observability",
    tags=["Admin Observability"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)

_TOOL_NAMES = {
    "retrieve": "RAG Search",
    "tool.inventory": "Inventory API",
    "tool.images": "Image Resolver",
    "generate": "Gemini Generation",
    "verify": "Answer Verifier",
}
_BUDGET_PATTERN = re.compile(rf"(?<!\d)(\d+(?:[.,]\d+)?)\s*({BUDGET_UNIT_ALTERNATION})(?!\w)", re.IGNORECASE)
_BILLION = 1_000_000_000


def _parse_trace_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _trace_runs_since(db: Session, cutoff: datetime) -> list[dict[str, Any]]:
    """Read durable traces first and merge legacy/debug JSONL records by run id."""

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    stored = (
        db.query(PipelineTraceRun)
        .filter(PipelineTraceRun.started_at >= cutoff)
        .order_by(PipelineTraceRun.started_at.desc())
        .limit(5_000)
        .all()
    )
    for row in stored:
        if not isinstance(row.payload, dict):
            continue
        raw = dict(row.payload)
        raw.setdefault("run_id", row.run_id)
        raw.setdefault("started_at", row.started_at.isoformat())
        rows.append(raw)
        seen.add(row.run_id)

    for raw in read_runs():
        started_at = _parse_trace_time(raw.get("started_at"))
        run_id = raw.get("run_id")
        if started_at is not None and started_at >= cutoff and run_id not in seen:
            rows.append(raw)
            if isinstance(run_id, str):
                seen.add(run_id)
    return sorted(rows, key=lambda row: str(row.get("started_at", "")), reverse=True)


def _step_status(step: dict[str, Any]) -> Literal["success", "error", "skipped"]:
    if step.get("skipped"):
        return "skipped"
    if step.get("ok") is False or step.get("error"):
        return "error"
    return "success"


def _step_detail(step: dict[str, Any]) -> str | None:
    if step.get("error"):
        return str(step["error"])
    if step.get("skipped"):
        return f"Bỏ qua: {step['skipped']}"
    if step.get("doc_count") is not None:
        return f"{step['doc_count']} tài liệu"
    if step.get("unit_count") is not None:
        return f"{step['unit_count']} sản phẩm"
    if step.get("image_count") is not None:
        return f"{step['image_count']} hình ảnh"
    if step.get("score") is not None:
        return f"Điểm {float(step['score']):.2f}"
    if step.get("attempt") is not None:
        return f"Lần {step['attempt']}"
    return None


def _to_trace(raw: dict[str, Any]) -> TraceSummaryResponse | None:
    started_at = _parse_trace_time(raw.get("started_at"))
    if started_at is None or not raw.get("run_id"):
        return None
    steps = []
    for step in raw.get("steps") or []:
        if not isinstance(step, dict) or not isinstance(step.get("name"), str):
            continue
        duration = step.get("duration_ms")
        steps.append(
            TraceStepResponse(
                name=step["name"],
                at_ms=float(step.get("at_ms") or 0),
                duration_ms=float(duration) if isinstance(duration, int | float) else None,
                status=_step_status(step),
                detail=_step_detail(step),
            )
        )

    outcome = str(raw.get("outcome") or "completed")
    if outcome == "completed" and any(step.status == "error" for step in steps):
        outcome = "degraded"
    verifier_score = raw.get("verifier_score")
    return TraceSummaryResponse(
        run_id=str(raw["run_id"]),
        started_at=started_at,
        duration_ms=float(raw.get("duration_ms") or 0),
        project_id=str(raw["project_id"]) if raw.get("project_id") is not None else None,
        clearance=str(raw.get("clearance") or "unknown"),
        outcome=outcome,
        verifier_score=float(verifier_score) if isinstance(verifier_score, int | float) else None,
        steps=steps,
    )


def _tool_metrics(runs: list[dict[str, Any]]) -> list[ToolReliabilityMetric]:
    buckets: dict[str, dict[str, Any]] = {key: {"calls": 0, "errors": 0, "latencies": []} for key in _TOOL_NAMES}
    for run in runs:
        for step in run.get("steps") or []:
            if not isinstance(step, dict) or step.get("name") not in buckets or step.get("skipped"):
                continue
            bucket = buckets[step["name"]]
            bucket["calls"] += 1
            if _step_status(step) == "error":
                bucket["errors"] += 1
            duration = step.get("duration_ms")
            if isinstance(duration, int | float):
                bucket["latencies"].append(float(duration))

    result = []
    for key, name in _TOOL_NAMES.items():
        bucket = buckets[key]
        calls = int(bucket["calls"])
        errors = int(bucket["errors"])
        latencies = bucket["latencies"]
        result.append(
            ToolReliabilityMetric(
                key=key,
                name=name,
                calls=calls,
                errors=errors,
                success_rate=round((calls - errors) / calls * 100, 1) if calls else None,
                average_latency_ms=round(sum(latencies) / len(latencies), 1) if latencies else None,
            )
        )
    return sorted(result, key=lambda row: (row.errors, row.calls), reverse=True)


def _token_metrics(
    db: Session,
    runs: list[dict[str, Any]],
    period_days: int,
    cutoff: datetime,
) -> TokenMonitoringMetric:
    today = date.today()
    daily: dict[date, dict[str, int]] = {
        today - timedelta(days=offset): {"input": 0, "output": 0} for offset in range(period_days)
    }

    usage_rows = db.query(LlmUsageEvent).filter(LlmUsageEvent.created_at >= cutoff).all()
    persisted_usage_ids = {row.usage_id for row in usage_rows}
    for row in usage_rows:
        if row.created_at.date() not in daily:
            continue
        daily[row.created_at.date()]["input"] += int(row.input_tokens or 0)
        daily[row.created_at.date()]["output"] += int(row.output_tokens or 0)

    for run in runs:
        started_at = _parse_trace_time(run.get("started_at"))
        if started_at is None or started_at.date() not in daily:
            continue
        for step in run.get("steps") or []:
            if not isinstance(step, dict) or step.get("name") != "llm.usage":
                continue
            usage_id = step.get("usage_id")
            if isinstance(usage_id, str) and usage_id in persisted_usage_ids:
                continue
            daily[started_at.date()]["input"] += int(step.get("input_tokens") or 0)
            daily[started_at.date()]["output"] += int(step.get("output_tokens") or 0)

    configured = bool(settings.token_input_cost_per_million_usd or settings.token_output_cost_per_million_usd)

    def cost(input_tokens: int, output_tokens: int) -> float:
        return round(
            input_tokens / 1_000_000 * settings.token_input_cost_per_million_usd
            + output_tokens / 1_000_000 * settings.token_output_cost_per_million_usd,
            4,
        )

    daily_rows = [
        TokenDailyMetric(
            date=day.isoformat(),
            input_tokens=counts["input"],
            output_tokens=counts["output"],
            estimated_cost_usd=cost(counts["input"], counts["output"]),
        )
        for day, counts in sorted(daily.items())
    ]
    input_total = sum(row.input_tokens for row in daily_rows)
    output_total = sum(row.output_tokens for row in daily_rows)
    total_cost = cost(input_total, output_total)
    return TokenMonitoringMetric(
        input_tokens=input_total,
        output_tokens=output_total,
        estimated_cost_usd=total_cost,
        projected_monthly_cost_usd=round(total_cost / period_days * 30, 4),
        cost_configured=configured,
        daily=daily_rows,
    )


def _severity(event: str) -> Literal["INFO", "WARN", "ERROR"]:
    lowered = event.lower()
    if any(part in lowered for part in ("failed", "failure", "error", "blocked", "crash")):
        return "ERROR"
    if any(part in lowered for part in ("warning", "rejected", "expired", "retry")):
        return "WARN"
    return "INFO"


def _audit_logs(rows: list[AuditLog], *, severity: str | None, module: str | None) -> list[AuditLogEntry]:
    result = []
    for row in rows:
        row_severity = _severity(row.event)
        row_module = row.event.split(".", 1)[0]
        if severity and row_severity != severity:
            continue
        if module and row_module != module:
            continue
        result.append(
            AuditLogEntry(
                id=row.id,
                timestamp=row.created_at,
                severity=row_severity,
                module=row_module,
                event=row.event,
                username=row.username,
                request_id=row.request_id,
            )
        )
    return result


def _budget_intents(db: Session, cutoff: datetime) -> list[IntentBucketMetric]:
    contents = [
        row[0]
        for row in db.query(Message.content)
        .filter(Message.sender == MessageSender.CUSTOMER, Message.created_at >= cutoff)
        .all()
    ]
    counts = Counter({"Dưới 3 tỷ": 0, "3–5 tỷ": 0, "5–10 tỷ": 0, "Trên 10 tỷ": 0})
    for content in contents:
        match = _BUDGET_PATTERN.search(content)
        if match is None:
            continue
        dong = parse_vnd(match.group(1), match.group(2), profile=Profile.CONVERSATIONAL)
        if dong is None:
            continue
        value = dong / _BILLION
        if value < 3:
            counts["Dưới 3 tỷ"] += 1
        elif value < 5:
            counts["3–5 tỷ"] += 1
        elif value <= 10:
            counts["5–10 tỷ"] += 1
        else:
            counts["Trên 10 tỷ"] += 1
    return [IntentBucketMetric(label=label, count=value) for label, value in counts.items()]


def _popular_projects(db: Session, cutoff: datetime) -> list[PopularProjectMetric]:
    rows = (
        db.query(ChatSession.project_id, func.count(ChatSession.id))
        .filter(ChatSession.project_id.is_not(None), ChatSession.created_at >= cutoff)
        .group_by(ChatSession.project_id)
        .order_by(func.count(ChatSession.id).desc())
        .limit(8)
        .all()
    )
    project_ids = [row[0] for row in rows]
    names = (
        {project.id: project.name for project in db.query(Project).filter(Project.id.in_(project_ids)).all()}
        if project_ids
        else {}
    )
    return [
        PopularProjectMetric(project_id=project_id, project_name=names.get(project_id, project_id), count=count)
        for project_id, count in rows
    ]


def _fallback_alerts(db: Session, cutoff: datetime) -> list[FallbackAlertResponse]:
    failures = (
        db.query(Message)
        .filter(
            Message.sender == MessageSender.AGENT,
            Message.verifier_score.is_not(None),
            Message.verifier_score < settings.verifier_threshold_sale,
            Message.created_at >= cutoff,
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .limit(20)
        .all()
    )
    alerts = []
    for failure in failures:
        previous = None
        if failure.session_id is not None:
            previous = (
                db.query(Message)
                .filter(
                    Message.session_id == failure.session_id,
                    Message.id < failure.id,
                    Message.sender.in_([MessageSender.CUSTOMER, MessageSender.SALE]),
                )
                .order_by(Message.id.desc())
                .first()
            )
        score = float(failure.verifier_score or 0)
        question = previous.content.strip()[:180] if previous else None
        alerts.append(
            FallbackAlertResponse(
                message_id=failure.id,
                session_id=failure.session_id,
                severity="critical" if score < 0.4 else "warning",
                verifier_score=score,
                failure_mode=failure.failure_mode,
                customer_question=question,
                created_at=failure.created_at,
            )
        )
    return alerts


@router.get("", response_model=ObservabilityOverviewResponse)
async def get_observability_overview(
    days: int = Query(default=14, ge=7, le=30),
    severity: str | None = Query(default=None, pattern="^(INFO|WARN|ERROR)$"),
    module: str | None = None,
    db: Session = Depends(get_db),
) -> ObservabilityOverviewResponse:
    now = utcnow()
    cutoff = now - timedelta(days=days)
    day_cutoff = now - timedelta(days=1)
    month_cutoff = now - timedelta(days=30)
    runs = _trace_runs_since(db, cutoff)

    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.created_at >= cutoff)
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .limit(500)
        .all()
    )
    modules = Counter(row.event.split(".", 1)[0] for row in audit_rows)
    trace_rows = [trace for raw in runs[:20] if (trace := _to_trace(raw)) is not None]

    dau = (
        db.query(func.count(func.distinct(AuditLog.user_id)))
        .filter(AuditLog.user_id.is_not(None), AuditLog.created_at >= day_cutoff)
        .scalar()
        or 0
    )
    mau = (
        db.query(func.count(func.distinct(AuditLog.user_id)))
        .filter(AuditLog.user_id.is_not(None), AuditLog.created_at >= month_cutoff)
        .scalar()
        or 0
    )
    waiting_sessions = db.query(ChatSession).filter(ChatSession.status == SessionStatus.WAITING_SALE).count()
    active_sessions = (
        db.query(ChatSession)
        .filter(ChatSession.status.in_([SessionStatus.WAITING_SALE, SessionStatus.SALE_HANDLING]))
        .count()
    )

    return ObservabilityOverviewResponse(
        generated_at=now,
        period_days=days,
        tracing_enabled=settings.observability_metrics_enabled or settings.tracing_enabled,
        tool_reliability=_tool_metrics(runs),
        users=UserMonitoringMetric(
            dau=int(dau),
            mau=int(mau),
            active_sessions=active_sessions,
            waiting_sessions=waiting_sessions,
        ),
        tokens=_token_metrics(db, runs, days, cutoff),
        most_used_modules=[ModuleUsageMetric(module=name, calls=count) for name, count in modules.most_common(8)],
        logs=_audit_logs(audit_rows, severity=severity, module=module)[:100],
        traces=trace_rows,
        budget_intents=_budget_intents(db, cutoff),
        popular_projects=_popular_projects(db, cutoff),
        fallback_alerts=_fallback_alerts(db, cutoff),
    )


@router.get("/traces/{run_id}", response_model=TraceSummaryResponse)
async def get_trace(run_id: str, db: Session = Depends(get_db)) -> TraceSummaryResponse:
    stored = db.query(PipelineTraceRun).filter(PipelineTraceRun.run_id == run_id).first()
    if stored is not None and isinstance(stored.payload, dict):
        trace = _to_trace(stored.payload)
        if trace is not None:
            return trace
    for raw in read_runs():
        if raw.get("run_id") == run_id:
            trace = _to_trace(raw)
            if trace is not None:
                return trace
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy Trace ID.")
