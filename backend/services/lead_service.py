"""Orchestrates lead scoring: gather the inputs, score, persist, record.

Split from `lead_scoring_service` the same way `agent_pipeline` is split from
`verifier_service` — the scoring maths stays a pure function that tests can drive directly,
while everything that touches Redis, MySQL or Gemini lives here.

`rescore_for_turn` never raises. A lead score is a nice-to-have ranking hint; a bug in it
must not turn a working customer answer into a 500, which is the same posture
`memory_service` and `search_criteria.load` already take.
"""

import logging

from sqlalchemy.orm import Session

from backend.core import tracing
from backend.core.audit import log_event
from backend.core.config import get_settings
from backend.core.enums import MessageSender
from backend.models.chat_session import ChatSession
from backend.models.lead import Lead
from backend.models.message import Message
from backend.models.user import User
from backend.repositories.lead import get_or_create_lead, update_lead_score
from backend.repositories.user import get_user_by_id
from backend.services import lead_scoring_service as scoring
from backend.services import search_criteria

logger = logging.getLogger(__name__)


def rescore_for_turn(db: Session, session: ChatSession, query: str) -> None:
    """Re-score the person behind `session` after they said `query`.

    Called from the ONE place every customer turn passes through, before any of the
    router's early returns — see `customer_chat.ask_in_customer_session`.
    """
    settings = get_settings()
    if not settings.lead_scoring_enabled:
        return
    try:
        _rescore(db, session, query, settings)
    except Exception:
        logger.warning("Lead scoring failed for session %s; leaving the previous tier.", session.id, exc_info=True)


def _rescore(db: Session, session: ChatSession, query: str, settings) -> None:
    lead = get_or_create_lead(db, customer_id=session.customer_id, visitor_token=session.visitor_token)
    if lead is None:
        return

    criteria = _criteria_for(session.id, query)
    turn_count = _customer_turn_count(db, session.id)

    user = get_user_by_id(db, session.customer_id) if session.customer_id is not None else None
    signals = scoring.collect_signals(
        query,
        criteria,
        latched=scoring.compatible_latched_flags((lead.signals or {}).get("flags"), lead.analysis_version),
        turn_count=turn_count,
        is_registered=session.customer_id is not None,
        has_phone=bool(user is not None and user.phone),
    )
    rule_score = scoring.score_rules(signals)

    soft = None
    if settings.lead_scoring_llm_enabled and scoring.should_enrich(
        rule_score,
        signals,
        turns_since_llm=(turn_count - lead.llm_scored_turn) if lead.llm_scored_turn is not None else None,
        hot_threshold=settings.lead_hot_threshold,
        warm_threshold=settings.lead_warm_threshold,
        min_turns=settings.lead_llm_min_turns,
    ):
        soft = scoring.enrich_with_llm(_recent_customer_turns(db, session.id, settings.lead_llm_max_history_turns))

    verdict = scoring.combine(
        rule_score,
        signals,
        soft,
        hot_threshold=settings.lead_hot_threshold,
        warm_threshold=settings.lead_warm_threshold,
    )
    update_lead_score(
        db, lead, verdict, turn_count=turn_count, project_id=session.project_id, llm_scored=soft is not None
    )

    tracing.step("lead.score", tier=verdict.tier, rule_score=rule_score, llm_called=soft is not None)
    log_event(
        "lead.scored",
        lead_id=lead.id,
        session_id=session.id,
        tier=verdict.tier,
        score=verdict.score,
        detection_method=verdict.detection_method,
        is_anonymous=session.customer_id is None,
    )


def rescore_after_claim(db: Session, lead, user) -> None:
    """Re-apply the rule score once an anonymous visitor becomes a known account.

    Registration adds two signals — `registered` and `has_phone` — without the person saying
    anything new, so nothing else would trigger a rescore until their next message. Rules
    only: no sentence was said, so there is nothing for the LLM to read.

    Never raises, for the same reason `rescore_for_turn` does not: this runs inside the
    registration request, and a ranking hint must not be able to fail a signup.
    """
    if lead is None or not get_settings().lead_scoring_enabled:
        return
    try:
        settings = get_settings()
        signals = scoring.signals_from_stored(
            scoring.compatible_latched_flags((lead.signals or {}).get("flags"), lead.analysis_version),
            turn_count=lead.turn_count,
            is_registered=True,
            has_phone=bool(user is not None and user.phone),
        )
        verdict = scoring.combine(
            scoring.score_rules(signals),
            signals,
            None,
            hot_threshold=settings.lead_hot_threshold,
            warm_threshold=settings.lead_warm_threshold,
        )
        update_lead_score(db, lead, verdict, turn_count=lead.turn_count, project_id=lead.project_id)
    except Exception:
        logger.warning("Post-registration rescore failed for lead %s.", lead.id, exc_info=True)


def rescore_stale_leads(db: Session, leads: list[Lead], users: dict[int, User]) -> None:
    """Upgrade persisted scores created by an older ruleset.

    Inbox rows can remain untouched for days, so waiting for another customer message leaves
    obsolete HOT badges visible after a scoring fix ships. Old intent flags are deliberately
    filtered through ``compatible_latched_flags``; only stable facts survive the upgrade.
    """
    settings = get_settings()
    if not settings.lead_scoring_enabled:
        return

    for lead in leads:
        if lead.analysis_version == scoring.ANALYSIS_VERSION:
            continue
        lead_id = lead.id
        try:
            user = users.get(lead.customer_id) if lead.customer_id is not None else None
            signals = scoring.signals_from_stored(
                scoring.compatible_latched_flags((lead.signals or {}).get("flags"), lead.analysis_version),
                turn_count=lead.turn_count,
                is_registered=lead.customer_id is not None,
                has_phone=bool(user is not None and user.phone),
            )
            verdict = scoring.combine(
                scoring.score_rules(signals),
                signals,
                None,
                hot_threshold=settings.lead_hot_threshold,
                warm_threshold=settings.lead_warm_threshold,
            )
            update_lead_score(db, lead, verdict, turn_count=lead.turn_count, project_id=lead.project_id)
        except Exception:
            db.rollback()
            logger.warning("Stale lead rescore failed for lead %s; leaving the previous tier.", lead_id, exc_info=True)


def _criteria_for(session_id: int, query: str) -> search_criteria.SearchCriteria:
    """This turn's criteria merged onto the session's stored ones — READ ONLY.

    `search_criteria.resolve` is deliberately not used: it persists, and `agent_pipeline`
    owns that state including its undo stack. Reading `load()` alone is not enough either —
    the pipeline only saves on refinement turns (`_criteria_resolve` builds a standalone
    object and discards it otherwise), so a budget stated in a first-mention question never
    reaches Redis. Merging here recovers it without writing anything back.
    """
    stored = search_criteria.SearchCriteria()
    try:
        stored, _ = search_criteria.load(session_id)
    except Exception:
        logger.debug("Could not load stored criteria for session %s.", session_id, exc_info=True)
    return search_criteria.merge_criteria(stored, search_criteria.parse_criteria(query))


def _customer_turn_count(db: Session, session_id: int) -> int:
    return db.query(Message).filter(Message.session_id == session_id, Message.sender == MessageSender.CUSTOMER).count()


def _recent_customer_turns(db: Session, session_id: int, limit: int) -> list[str]:
    """The customer's own words only.

    The AI's replies are deliberately excluded: feeding them back would let one hallucinated
    "anh/chị cần mua gấp phải không ạ?" score itself, the same trap `memory_service` documents
    for long-term memory.
    """
    rows = (
        db.query(Message.content)
        .filter(Message.session_id == session_id, Message.sender == MessageSender.CUSTOMER)
        .order_by(Message.id.desc())
        .limit(limit)
        .all()
    )
    return [content for (content,) in reversed(rows)]
