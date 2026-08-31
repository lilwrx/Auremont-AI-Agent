from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from backend.core.config import get_settings
from backend.core.deps import require_role
from backend.core.enums import LeadTier, UserRole
from backend.core.mysql_client import get_db
from backend.models.chat_session import ChatSession
from backend.models.conflict_flag import ConflictFlag
from backend.models.document import Document
from backend.models.feedback import Feedback
from backend.models.hitl_log import HitlLog
from backend.models.lead import Lead
from backend.models.message import Message
from backend.models.project import Project
from backend.models.user import User
from backend.schemas.admin_dashboard import (
    BusinessDashboardResponse,
    LeadEnrichmentStats,
    LeadStatsResponse,
    LeadTierCounts,
    LeadTrendPoint,
)
from backend.services.document_category_service import document_has_category
from backend.services.document_coverage_service import (
    COVERAGE_CATEGORIES,
    document_coverage_state,
    document_matches_project_scope,
    project_scope_aliases,
)

router = APIRouter(prefix="/admin/stats", tags=["Admin Stats"], dependencies=[Depends(require_role(UserRole.ADMIN))])

TREND_DAYS = 14


def _dashboard_timezone() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().business_timezone)
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def _utc_boundary(day: date, zone: ZoneInfo) -> datetime:
    """Convert a local midnight to the UTC-naive format stored by SQLAlchemy."""
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(UTC).replace(tzinfo=None)


def _local_date(value: datetime, zone: ZoneInfo) -> date:
    return value.replace(tzinfo=UTC).astimezone(zone).date()


def _period_metrics(
    db: Session,
    sessions: list[ChatSession],
    messages: list[Message],
    sale_by_session: dict[int, int | None],
) -> dict[str, Any]:
    """Build one internally consistent snapshot for a group of sessions."""
    agent_messages = [row for row in messages if row.sender == "agent"]
    sale_messages = [row for row in messages if row.sender == "sale"]
    raw_feedback_rows = (
        db.query(Feedback).filter(Feedback.message_id.in_([row.id for row in agent_messages])).all()
        if agent_messages
        else []
    )
    latest_feedback: dict[int, Feedback] = {}
    for row in sorted(raw_feedback_rows, key=lambda item: (item.created_at, item.id)):
        latest_feedback[row.message_id] = row
    feedback_rows = list(latest_feedback.values())

    helpful_count = sum(1 for row in feedback_rows if row.type == "helpful")
    helpful_rate = helpful_count / len(feedback_rows) if feedback_rows else None
    verified_scores = [row.verifier_score for row in agent_messages if row.verifier_score is not None]
    verifier_avg = sum(verified_scores) / len(verified_scores) if verified_scores else None
    hitl_required = [row for row in agent_messages if row.requires_hitl]
    hitl_message_ids = [row.id for row in hitl_required]
    hitl_confirmed = (
        db.query(func.count(func.distinct(HitlLog.message_id)))
        .filter(HitlLog.message_id.in_(hitl_message_ids), HitlLog.confirmed_at.isnot(None))
        .scalar()
        if hitl_message_ids
        else 0
    )
    active_sale_ids = {row.sale_id for row in sessions if row.sale_id is not None}
    active_sale_ids.update(
        owner
        for row in sale_messages
        if row.session_id is not None and (owner := sale_by_session.get(row.session_id)) is not None
    )

    return {
        "agent_messages": agent_messages,
        "sale_messages": sale_messages,
        "feedback_rows": feedback_rows,
        "summary": {
            "sessions": len(sessions),
            "customers": sum(1 for row in sessions if row.customer_name and row.customer_name.strip()),
            "questions": len(sale_messages),
            "active_sales": len(active_sale_ids),
            "helpful_rate": helpful_rate,
            "verifier_avg": verifier_avg,
            "hitl_required": len(hitl_required),
            "hitl_confirmed": hitl_confirmed,
        },
    }


def _cumulative_counts(created_dates: list[date], days: int) -> list[int]:
    """Total rows that existed by the end of each day, used to render growth trend charts."""
    start = date.today() - timedelta(days=days - 1)
    per_day: dict[date, int] = {}
    for d in created_dates:
        per_day[d] = per_day.get(d, 0) + 1

    running = sum(count for d, count in per_day.items() if d < start)
    result = []
    for i in range(days):
        day = start + timedelta(days=i)
        running += per_day.get(day, 0)
        result.append(running)
    return result


def _open_conflicts_trend(rows: list[tuple[date, date | None]], days: int) -> list[int]:
    """Number of flags still open as of the end of each day (created, not yet resolved by that point)."""
    start = date.today() - timedelta(days=days - 1)
    result = []
    for i in range(days):
        day = start + timedelta(days=i)
        open_count = sum(1 for created, resolved in rows if created <= day and (resolved is None or resolved > day))
        result.append(open_count)
    return result


@router.get("/trends")
async def get_admin_trends(db: Session = Depends(get_db)) -> dict:
    """Sparkline data for AdminHome — computed only from fields that actually exist
    (created_at/resolved_at); does not fabricate numbers for faithfulness/relevancy
    since the real eval pipeline is not wired up yet."""
    doc_dates = [row[0].date() for row in db.query(Document.created_at).all()]
    conflict_rows = [
        (row[0].date(), row[1].date() if row[1] else None)
        for row in db.query(ConflictFlag.created_at, ConflictFlag.resolved_at).all()
    ]

    return {
        "documents": _cumulative_counts(doc_dates, TREND_DAYS),
        "open_conflicts": _open_conflicts_trend(conflict_rows, TREND_DAYS),
    }


@router.get("/business", response_model=BusinessDashboardResponse)
async def get_business_dashboard(
    days: int = Query(default=14, ge=7, le=90),
    project_id: str | None = None,
    sale_id: int | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Business overview computed only from data already captured by SalesMate.

    A consultation session is the closest current proxy for a customer interaction;
    revenue, contracts and conversion rate are intentionally omitted because the
    product does not store those facts yet.
    """
    zone = _dashboard_timezone()
    today = datetime.now(UTC).astimezone(zone).date()
    start_day = today - timedelta(days=days - 1)
    start_at = _utc_boundary(start_day, zone)
    end_at = _utc_boundary(today + timedelta(days=1), zone)
    previous_start_day = start_day - timedelta(days=days)
    previous_start_at = _utc_boundary(previous_start_day, zone)

    official_sales = db.query(User).filter(User.role == "sale", ~User.username.like("e2e_sale_%")).all()
    sale_names = {row.id: row.username for row in official_sales}
    official_sale_ids = set(sale_names)
    session_scope: list[ColumnElement[bool]] = [ChatSession.sale_id.in_(official_sale_ids)]
    if project_id:
        session_scope.append(ChatSession.project_id == project_id)
    if sale_id:
        session_scope.append(ChatSession.sale_id == sale_id)

    sessions = (
        db.query(ChatSession)
        .filter(*session_scope, ChatSession.created_at >= start_at, ChatSession.created_at < end_at)
        .all()
        if official_sale_ids
        else []
    )
    previous_sessions = (
        db.query(ChatSession)
        .filter(*session_scope, ChatSession.created_at >= previous_start_at, ChatSession.created_at < start_at)
        .all()
        if official_sale_ids
        else []
    )
    period_message_rows = (
        db.query(Message, ChatSession.sale_id)
        .join(ChatSession, Message.session_id == ChatSession.id)
        .filter(
            *session_scope,
            Message.created_at >= previous_start_at,
            Message.created_at < end_at,
        )
        .all()
        if official_sale_ids
        else []
    )
    period_messages = [row[0] for row in period_message_rows]
    sale_by_session = {row[0].session_id: row[1] for row in period_message_rows if row[0].session_id is not None}
    current_messages = [row for row in period_messages if start_at <= row.created_at < end_at]
    previous_messages = [row for row in period_messages if previous_start_at <= row.created_at < start_at]
    current_period = _period_metrics(db, sessions, current_messages, sale_by_session)
    agent_messages = current_period["agent_messages"]
    sale_messages = current_period["sale_messages"]
    feedback_rows = current_period["feedback_rows"]
    previous_summary = _period_metrics(db, previous_sessions, previous_messages, sale_by_session)["summary"]

    activity = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        day_sessions = [row for row in sessions if _local_date(row.created_at, zone) == day]
        activity.append(
            {
                "date": day.isoformat(),
                "sessions": len(day_sessions),
                "questions": sum(1 for row in sale_messages if _local_date(row.created_at, zone) == day),
            }
        )

    projects = db.query(Project).all()
    project_names = {row.id: row.name for row in projects}
    project_counts: dict[str, int] = {}
    unknown_project_count = 0
    for row in sessions:
        if not row.project_id:
            unknown_project_count += 1
            continue
        project_counts[row.project_id] = project_counts.get(row.project_id, 0) + 1
    top_projects: list[dict[str, Any]] = [
        {"project_id": project_id, "name": project_names.get(project_id, project_id), "sessions": count}
        for project_id, count in sorted(project_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ]
    if unknown_project_count:
        top_projects.append({"project_id": None, "name": "Chưa xác định dự án", "sessions": unknown_project_count})
        top_projects.sort(key=lambda item: (-item["sessions"], item["name"]))
        top_projects = top_projects[:6]

    sale_counts: dict[int, dict[str, int]] = {}
    for row in sessions:
        if row.sale_id not in official_sale_ids:
            continue
        sale_counts.setdefault(row.sale_id, {"sessions": 0, "customers": 0})
        sale_counts[row.sale_id]["sessions"] += 1
        if row.customer_name and row.customer_name.strip():
            sale_counts[row.sale_id]["customers"] += 1
    for row in sale_messages:
        sale_id = sale_by_session.get(row.session_id) if row.session_id is not None else None
        if sale_id in official_sale_ids:
            sale_counts.setdefault(sale_id, {"sessions": 0, "customers": 0})
            sale_counts[sale_id].setdefault("questions", 0)
            sale_counts[sale_id]["questions"] += 1
    top_sales = [
        {
            "sale_id": sale_id,
            "username": sale_names.get(sale_id, f"Sale #{sale_id}"),
            "sessions": counts["sessions"],
            "customers": counts["customers"],
            "questions": counts.get("questions", 0),
        }
        for sale_id, counts in sorted(sale_counts.items(), key=lambda item: (-item[1]["sessions"], item[0]))[:5]
    ]

    feedback_distribution = {"helpful": 0, "wrong": 0, "incomplete": 0, "unrated": 0}
    rated_message_ids: set[int] = set()
    for row in feedback_rows:
        if row.type in feedback_distribution:
            feedback_distribution[row.type] += 1
        rated_message_ids.add(row.message_id)
    feedback_distribution["unrated"] = sum(1 for row in agent_messages if row.id not in rated_message_ids)

    quality_trend = []
    for offset in range(days):
        day = start_day + timedelta(days=offset)
        day_answers = [row for row in agent_messages if _local_date(row.created_at, zone) == day]
        faithfulness = [row.faithfulness for row in day_answers if row.faithfulness is not None]
        relevancy = [row.answer_relevancy for row in day_answers if row.answer_relevancy is not None]
        quality_trend.append(
            {
                "date": day.isoformat(),
                "faithfulness": sum(faithfulness) / len(faithfulness) if faithfulness else None,
                "relevancy": sum(relevancy) / len(relevancy) if relevancy else None,
            }
        )

    documents = db.query(Document).all()
    document_coverage: list[dict[str, Any]] = []
    coverage_projects = [project for project in projects if not project_id or project.id == project_id]
    for project in coverage_projects:
        project_aliases = project_scope_aliases(project)
        project_documents = [row for row in documents if document_matches_project_scope(row, project, project_aliases)]
        categories = {}
        for category in COVERAGE_CATEGORIES:
            matching = [row for row in project_documents if document_has_category(row, category)]
            categories[category] = document_coverage_state(
                matching,
                retrieval_project_id=project.id,
            )
        document_coverage.append(
            {
                "project_id": project.id,
                "name": project.name,
                "categories": categories,
                "ready_count": sum(1 for state in categories.values() if state == "ready"),
            }
        )
    document_coverage.sort(key=lambda item: (-item["ready_count"], item["name"]))

    selected_coverage_project = next((project for project in projects if project.id == project_id), None)
    ready_documents = sum(
        1
        for document in documents
        if document.is_current
        and document.status == "completed"
        and document.review_status == "approved"
        and (selected_coverage_project is None or document.project_id == selected_coverage_project.id)
    )
    summary = current_period["summary"]
    summary["ready_documents"] = ready_documents

    return {
        "period_days": days,
        "period": {
            "current_start": start_day.isoformat(),
            "current_end": today.isoformat(),
            "previous_start": previous_start_day.isoformat(),
            "previous_end": (start_day - timedelta(days=1)).isoformat(),
            "timezone": zone.key,
        },
        "applied_filters": {"project_id": project_id, "sale_id": sale_id},
        "filter_options": {
            "projects": [{"id": row.id, "name": row.name} for row in projects],
            "sales": [{"id": row.id, "username": row.username} for row in official_sales],
        },
        "verifier_threshold": get_settings().verifier_threshold_sale,
        "summary": summary,
        "previous_summary": previous_summary,
        "activity": activity,
        "top_projects": top_projects,
        "top_sales": top_sales,
        "feedback_distribution": feedback_distribution,
        "quality_trend": quality_trend,
        "hitl_funnel": {
            "answers": len(agent_messages),
            "required": summary["hitl_required"],
            "confirmed": summary["hitl_confirmed"],
        },
        "document_coverage": document_coverage[:8],
    }


@router.get("/leads", response_model=LeadStatsResponse)
async def get_lead_stats(
    days: int = Query(default=14, ge=7, le=90),
    project_id: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    """Lead capture and scoring over the last `days`.

    Deliberately NOT part of /business: that endpoint scopes everything to sessions owned by
    an official Sale, while a customer-chat session has no Sale until it is claimed. Merging
    the two would make one response describe two different populations.
    """
    zone = _dashboard_timezone()
    today = datetime.now(UTC).astimezone(zone).date()
    start_at = _utc_boundary(today - timedelta(days=days - 1), zone)

    query = db.query(Lead).filter(Lead.scored_at.isnot(None), Lead.scored_at >= start_at)
    if project_id:
        query = query.filter(Lead.project_id == project_id)
    leads = query.all()

    totals = LeadTierCounts(
        hot=sum(1 for lead in leads if lead.tier == LeadTier.HOT),
        warm=sum(1 for lead in leads if lead.tier == LeadTier.WARM),
        cold=sum(1 for lead in leads if lead.tier == LeadTier.COLD),
        total=len(leads),
    )

    by_day: dict[str, LeadTrendPoint] = {}
    for offset in range(days):
        key = (today - timedelta(days=days - 1 - offset)).isoformat()
        by_day[key] = LeadTrendPoint(date=key)
    for lead in leads:
        if lead.scored_at is None:
            continue
        key = lead.scored_at.replace(tzinfo=UTC).astimezone(zone).date().isoformat()
        point = by_day.get(key)
        if point is not None:
            setattr(point, str(lead.tier), getattr(point, str(lead.tier)) + 1)

    registered = sum(1 for lead in leads if lead.customer_id is not None)
    customer_ids = [lead.customer_id for lead in leads if lead.customer_id is not None]
    contactable = (
        db.query(User).filter(User.id.in_(customer_ids), User.phone.isnot(None)).count() if customer_ids else 0
    )
    llm_calls = sum(1 for lead in leads if lead.detection_method == "rule+llm")

    return {
        "period_days": days,
        "totals": totals,
        "trend": list(by_day.values()),
        "registered": registered,
        "anonymous": len(leads) - registered,
        "contactable": contactable,
        "contact_rate": round(contactable / len(leads), 3) if leads else 0.0,
        "avg_score": round(sum(lead.score for lead in leads) / len(leads), 1) if leads else 0.0,
        "llm_enrichment": LeadEnrichmentStats(
            scored=len(leads),
            llm_calls=llm_calls,
            call_rate=round(llm_calls / len(leads), 3) if leads else 0.0,
        ),
    }
