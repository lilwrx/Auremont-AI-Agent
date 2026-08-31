from typing import Any

from sqlalchemy.orm import Session

from backend.core.enums import LeadTier
from backend.models.lead import Lead
from backend.services.lead_scoring_service import LeadVerdict
from backend.utils.time import utcnow


def get_or_create_lead(db: Session, *, customer_id: int | None = None, visitor_token: str | None = None) -> Lead | None:
    """The one lead row for this person, created on first sight.

    Returns None when neither identifier is supplied — a Sale's own AI-consult session has
    no customer behind it and must never produce a lead.
    """
    if customer_id is None and visitor_token is None:
        return None

    query = db.query(Lead)
    lead = (
        query.filter(Lead.customer_id == customer_id).first()
        if customer_id is not None
        else query.filter(Lead.visitor_token == visitor_token).first()
    )
    if lead is not None:
        return lead

    lead = Lead(customer_id=customer_id, visitor_token=visitor_token if customer_id is None else None)
    db.add(lead)
    db.commit()
    db.refresh(lead)
    return lead


def update_lead_score(
    db: Session,
    lead: Lead,
    verdict: LeadVerdict,
    *,
    turn_count: int,
    project_id: str | None = None,
    llm_scored: bool = False,
) -> Lead:
    lead.tier = verdict.tier
    lead.score = verdict.score
    lead.rule_score = verdict.rule_score
    new_signals = dict(verdict.signals)
    if "llm_reason" not in new_signals and lead.signals and lead.signals.get("llm_reason"):
        new_signals["llm_reason"] = lead.signals["llm_reason"]
    lead.signals = new_signals
    lead.detection_method = verdict.detection_method
    lead.analysis_version = verdict.signals.get("analysis_version")
    lead.turn_count = turn_count
    lead.scored_at = utcnow()
    if project_id and not lead.project_id:
        lead.project_id = project_id
    if llm_scored:
        lead.soft_score = verdict.soft_score
        lead.urgency = verdict.urgency
        lead.purpose = verdict.purpose
        lead.confidence = verdict.confidence
        lead.llm_scored_turn = turn_count
        lead.llm_scored_at = utcnow()
    db.commit()
    db.refresh(lead)
    return lead


def claim_anonymous_lead(db: Session, *, visitor_token: str, customer_id: int) -> Lead | None:
    """Move a visitor's accumulated score onto their new account.

    Mirrors `claim_or_merge_anonymous_session`. A first-time registration simply transfers
    ownership; someone who already had an account keeps the higher score and the union of
    the latched signals, because both rows describe the same person and a signal they gave
    in either browser is still a signal they gave.
    """
    anonymous = db.query(Lead).filter(Lead.visitor_token == visitor_token).first()
    if anonymous is None:
        return None

    existing = db.query(Lead).filter(Lead.customer_id == customer_id).first()
    if existing is None:
        anonymous.customer_id = customer_id
        anonymous.visitor_token = None
        db.commit()
        db.refresh(anonymous)
        return anonymous

    if anonymous.score > existing.score:
        existing.tier = anonymous.tier
        existing.score = anonymous.score
        existing.rule_score = anonymous.rule_score
    existing.signals = _merge_signals(existing.signals, anonymous.signals)
    existing.turn_count = existing.turn_count + anonymous.turn_count
    if not existing.project_id and anonymous.project_id:
        existing.project_id = anonymous.project_id
    if anonymous.created_at < existing.created_at:
        existing.created_at = anonymous.created_at
    db.delete(anonymous)
    db.commit()
    db.refresh(existing)
    return existing


def _merge_signals(target: dict[str, Any] | None, source: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(target or {})
    flags = dict(merged.get("flags") or {})
    for name, fired in (source or {}).get("flags", {}).items():
        flags[name] = bool(flags.get(name)) or bool(fired)
    merged["flags"] = flags
    return merged


def reset_lead_score(db: Session, lead: Lead) -> Lead:
    """Drop the conversational evidence while keeping the person.

    Called when a customer clears their chat: the signals were derived from messages they
    just erased, so keeping the tier would be a verdict with no evidence behind it. The row
    and its identity survive — clearing a conversation is not a request to delete an account.
    """
    lead.tier = LeadTier.COLD
    lead.score = 0
    lead.rule_score = 0
    lead.soft_score = None
    lead.urgency = None
    lead.purpose = None
    lead.confidence = None
    lead.signals = None
    lead.detection_method = "rule"
    lead.turn_count = 0
    lead.llm_scored_turn = None
    lead.llm_scored_at = None
    lead.scored_at = None
    db.commit()
    db.refresh(lead)
    return lead


def get_lead_for_customer(db: Session, customer_id: int) -> Lead | None:
    return db.query(Lead).filter(Lead.customer_id == customer_id).first()


def list_leads_for_customers(db: Session, customer_ids: list[int]) -> dict[int, Lead]:
    """Batched, because the live inbox renders one row per session and is polled every 5s."""
    if not customer_ids:
        return {}
    rows = db.query(Lead).filter(Lead.customer_id.in_(customer_ids)).all()
    return {lead.customer_id: lead for lead in rows if lead.customer_id is not None}
