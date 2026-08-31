import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypeVar

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.deps import require_role
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.models.observability import PipelineTraceRun
from backend.repositories.audit_log import count_audit_logs, list_audit_logs
from backend.repositories.feedback import (
    get_average_verifier_scores,
    get_question_for_answer,
    list_top_failed,
)
from backend.schemas.admin_eval import (
    ArtifactStatus,
    DeepEvalArtifactResponse,
    DeepEvalReportResponse,
    EvalReportsResponse,
    PipelineArtifactSource,
    PipelineEvalArtifactResponse,
    PipelineEvalReportResponse,
)
from backend.utils.time import utcnow
from eval.graders import build_report

router = APIRouter(prefix="/admin/eval", tags=["Admin Eval"], dependencies=[Depends(require_role(UserRole.ADMIN))])

_MAX_REPORT_BYTES = 5 * 1024 * 1024
_ReportModel = TypeVar("_ReportModel", bound=BaseModel)


def _read_report(
    path_value: str, model: type[_ReportModel]
) -> tuple[ArtifactStatus, datetime | None, _ReportModel | None]:
    path = Path(path_value)
    try:
        stat = path.stat()
        if not path.is_file() or stat.st_size > _MAX_REPORT_BYTES:
            return "invalid", None, None
        payload = json.loads(path.read_text(encoding="utf-8"))
        report = model.model_validate(payload)
    except FileNotFoundError:
        return "missing", None, None
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        return "invalid", None, None

    generated_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)
    return "ready", generated_at, report


def _artifact_message(status: ArtifactStatus, label: str) -> str | None:
    if status == "missing":
        return f"Chưa có báo cáo {label}."
    if status == "invalid":
        return f"Báo cáo {label} không đọc được hoặc không đúng định dạng."
    return None


def _pipeline_report_from_traces(
    db: Session, limit: int = 1000
) -> tuple[datetime | None, PipelineEvalReportResponse | None]:
    rows = db.query(PipelineTraceRun).order_by(PipelineTraceRun.started_at.desc()).limit(limit).all()
    payloads = [row.payload for row in reversed(rows) if isinstance(row.payload, dict)]
    if not payloads:
        return None, None

    report = PipelineEvalReportResponse.model_validate(build_report(payloads))
    generated_at = rows[0].started_at
    if generated_at.tzinfo is None:
        generated_at = generated_at.replace(tzinfo=UTC)
    return generated_at, report


@router.get("/scores")
async def get_eval_scores(db: Session = Depends(get_db)) -> dict:
    """Faithfulness/Answer Relevancy dashboard + the top failed AI answers.

    The averages come from the scores the Verifier Agent recorded on each answer as it was
    generated, not from an offline DeepEval batch: those are the scores that actually
    gated what a Sale was shown. `eval/` stays the place for offline DeepEval runs over a
    fixed test set.
    """
    faithfulness_avg, answer_relevancy_avg = get_average_verifier_scores(db)

    top_failed = []
    for message_id, count in list_top_failed(db, limit=10):
        question = get_question_for_answer(db, message_id)
        if question is None:
            continue
        top_failed.append({"message_id": message_id, "question": question, "feedback_count": count})

    return {
        "faithfulness_avg": faithfulness_avg,
        "answer_relevancy_avg": answer_relevancy_avg,
        "top_failed_questions": top_failed,
    }


@router.get("/reports", response_model=EvalReportsResponse)
async def get_eval_reports(db: Session = Depends(get_db)) -> EvalReportsResponse:
    """Return the latest offline quality artifacts without running either evaluator.

    DeepEval can spend many judge calls, so the Admin page only reads its latest report.
    Raw case details are deliberately excluded by the response models; aggregates and
    short failure reasons are enough for triage without exposing complete conversations.
    """

    deep_status, deep_generated_at, deep_report = _read_report(settings.deepeval_report_path, DeepEvalReportResponse)
    eval_status, eval_generated_at, eval_report = _read_report(
        settings.evaluation_report_path, PipelineEvalReportResponse
    )
    eval_source: PipelineArtifactSource | None = "artifact" if eval_status == "ready" else None
    if eval_status == "missing":
        eval_generated_at, eval_report = _pipeline_report_from_traces(db)
        if eval_report is not None:
            eval_status = "ready"
            eval_source = "live_traces"

    return EvalReportsResponse(
        deepeval=DeepEvalArtifactResponse(
            status=deep_status,
            source="artifact" if deep_status == "ready" else None,
            generated_at=deep_generated_at,
            report=deep_report,
            message=_artifact_message(deep_status, "DeepEval"),
        ),
        evaluation=PipelineEvalArtifactResponse(
            status=eval_status,
            source=eval_source,
            generated_at=eval_generated_at,
            report=eval_report,
            message=_artifact_message(eval_status, "Pipeline Evaluation"),
        ),
    )


@router.get("/audit")
async def get_audit_log(
    event: str | None = Query(default=None, description="Exact event name, e.g. auth.login.failure"),
    user_id: int | None = Query(default=None),
    days: int | None = Query(default=None, ge=1, le=365, description="Only events from the last N days"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict:
    """Business-event trail, newest first.

    The stdout log is the place to debug what broke five minutes ago; this is the
    place to answer who did what, weeks later, after the container that served
    the request is long gone.
    """
    since = utcnow() - timedelta(days=days) if days is not None else None

    rows = list_audit_logs(db, event=event, user_id=user_id, since=since, limit=limit, offset=offset)

    return {
        "total": count_audit_logs(db, event=event, since=since),
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": row.id,
                "event": row.event,
                "user_id": row.user_id,
                "username": row.username,
                "request_id": row.request_id,
                "created_at": row.created_at,
                "payload": row.payload,
            }
            for row in rows
        ],
    }
