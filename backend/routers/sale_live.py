"""Live handoff queue: a customer session a Sale has taken over from the AI.

Deliberately a separate router/prefix from `sale_chat.py` (the Sale's own AI-consult flow)
rather than folded into it — a claimed session carries BOTH `sale_id` and `customer_id` (see
ChatSession's docstring), which does not fit `sale_chat.py`'s ownership check (`sale_id`
only) or its `/sale/sessions/{id}/messages` endpoint (which calls the AI pipeline — the one
thing that must never happen on a session a Sale is chatting through live).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.audit import log_event, truncate
from backend.core.config import get_settings
from backend.core.deps import require_role
from backend.core.enums import (
    DocumentVisibility,
    LeadPurpose,
    LeadTier,
    LeadUrgency,
    MessageSender,
    SessionChannel,
    SessionStatus,
    UserRole,
)
from backend.core.gemini_client import is_gemini_quota_error
from backend.core.mysql_client import get_db
from backend.models.chat_session import ChatSession
from backend.models.lead import Lead
from backend.models.message import Message
from backend.models.user import User
from backend.repositories.chat_session import (
    claim_for_sale,
    get_latest_customer_session,
    get_session,
    list_sessions_handled_by_sale,
    list_waiting_sessions,
    return_to_bot,
)
from backend.repositories.lead import get_lead_for_customer, list_leads_for_customers
from backend.repositories.message import create_message, history_for_pipeline, list_messages_for_session
from backend.repositories.user import get_user_by_id, list_users_by_ids
from backend.schemas.customer_summary import CustomerConversationSummaryResponse
from backend.schemas.message import MessageResponse
from backend.schemas.sale_live import (
    LeadDetailResponse,
    LeadSignalDetail,
    LiveInboxEntry,
    SaleLiveMessageRequest,
    SaleSuggestResponse,
)
from backend.services import (
    agent_pipeline,
    customer_summary_service,
    lead_scoring_service,
    lead_service,
    memory_service,
)
from backend.utils.time import utcnow

router = APIRouter(
    prefix="/sale/live-inbox",
    tags=["Sale Live Inbox"],
    dependencies=[Depends(require_role(UserRole.SALE, UserRole.ADMIN))],
)

_HANDOFF_ENDED_MESSAGE = (
    "Chuyên viên đã kết thúc phiên hỗ trợ trực tiếp. Bạn có thể tiếp tục hỏi Auremont AI bất cứ lúc nào nhé!"
)


def _customer_label(user: User | None, session: ChatSession) -> str:
    if user is None:
        return f"Khách #{session.customer_id}"
    return user.full_name or user.email


def _owned_live_session(db: Session, session_id: int, user: User) -> ChatSession:
    """404 unless this Sale is the one who claimed this session — same "don't reveal which
    ids exist" posture as `sale_chat._owned_session`.

    The `channel == LIVE` check is the second lock on customer privacy: a Sale is never
    shown the customer's AI conversation, and every read/write in this router goes through
    here, so passing an AI session's id gets the same 404 as an id that doesn't exist.
    """
    session = get_session(db, session_id)
    if (
        session is None
        or session.sale_id != user.id
        or session.customer_id is None
        or session.channel != SessionChannel.LIVE
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


def _to_entry(
    db: Session,
    session: ChatSession,
    *,
    users: dict[int, User] | None = None,
    leads: dict[int, Lead] | None = None,
) -> LiveInboxEntry:
    messages = list_messages_for_session(db, session.id)
    preview = truncate(messages[-1].content, limit=80) if messages else ""

    user = (users or {}).get(session.customer_id) if session.customer_id else None
    if user is None and session.customer_id and users is None:
        user = get_user_by_id(db, session.customer_id)
    lead = (leads or {}).get(session.customer_id) if session.customer_id else None
    if lead is None and session.customer_id and leads is None:
        lead = get_lead_for_customer(db, session.customer_id)

    return LiveInboxEntry(
        session_id=session.id,
        customer_label=_customer_label(user, session),
        last_message_preview=preview or "",
        waiting_since=session.handoff_requested_at,
        lead_tier=LeadTier(lead.tier) if lead else LeadTier.COLD,
        lead_score=lead.score if lead else 0,
        lead_reason=_lead_reason(lead),
        customer_name=user.full_name if user else None,
        customer_phone=user.phone if user else None,
    )


def _lead_reason(lead: Lead | None) -> str | None:
    """One short Vietnamese line naming the signals behind the tier."""
    if lead is None or not lead.signals:
        return None
    fired = [name for name, value in (lead.signals.get("flags") or {}).items() if value]
    labels = [_SIGNAL_LABELS[name] for name in fired if name in _SIGNAL_LABELS]
    return " · ".join(labels) if labels else None


_SIGNAL_LABELS = {
    "transaction_ready": "Đã yêu cầu bước giao dịch cụ thể",
    "consideration_intent": "Đang cân nhắc căn / phương án thanh toán",
    "stated_budget": "Đã nêu ngân sách",
    "closing_intent": "Muốn nhận tài liệu / đặt lịch / được liên hệ",
    "wants_human": "Xin gặp tư vấn viên",
    "near_term_timeline": "Có thời gian mua / đi xem gần",
    "named_unit_code": "Hỏi đúng mã căn cụ thể",
    "criteria_known": "Đã nêu tiêu chí tìm căn",
    "three_filters": "Đã lọc theo từ 3 tiêu chí trở lên",
    "registered": "Đã tạo tài khoản",
    "has_phone": "Đã có số điện thoại",
    "engaged": "Đã hỏi từ 6 lượt trở lên",
    "purpose_known": "Đã nói rõ mục đích ở/đầu tư",
    "household_known": "Đã nói số người trong gia đình",
}


def _decorate(db: Session, sessions: list[ChatSession]) -> list[LiveInboxEntry]:
    """Batch the user and lead lookups.

    Both list endpoints are polled every 5 seconds by every logged-in Sale, so a per-row
    query for the label plus another for the tier is an N+1 that grows with the queue.
    """
    customer_ids = [s.customer_id for s in sessions if s.customer_id is not None]
    users = list_users_by_ids(db, customer_ids)
    leads = list_leads_for_customers(db, customer_ids)
    lead_service.rescore_stale_leads(db, list(leads.values()), users)
    return [_to_entry(db, session, users=users, leads=leads) for session in sessions]


def _inbox_order(entry: LiveInboxEntry, fairness_minutes: int) -> tuple[int, int, float]:
    """Starved first, then hottest, then longest-waiting.

    Tier-first alone lets a steady trickle of HOT leads starve a COLD customer indefinitely —
    they are still a real person who asked for a human and is watching a spinner. Waiting
    past the fairness window outranks any tier.
    """
    waiting_since = entry.waiting_since
    waited = (utcnow() - waiting_since).total_seconds() if waiting_since else 0.0
    starved = 1 if waited >= fairness_minutes * 60 else 0
    tier_rank = {LeadTier.HOT: 2, LeadTier.WARM: 1, LeadTier.COLD: 0}[entry.lead_tier]
    return (-starved, -tier_rank, -waited)


@router.get("", response_model=list[LiveInboxEntry])
async def list_waiting(db: Session = Depends(get_db)) -> list[LiveInboxEntry]:
    """Ordered by business priority here rather than in the repository.

    `list_waiting_sessions` documents itself as FIFO on `handoff_requested_at`; burying a
    tier ranking inside it would make that docstring a lie for every other caller.
    """
    fairness = get_settings().lead_inbox_fairness_minutes
    entries = _decorate(db, list_waiting_sessions(db))
    return sorted(entries, key=lambda entry: _inbox_order(entry, fairness))


@router.get("/mine", response_model=list[LiveInboxEntry])
async def list_mine(
    db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> list[LiveInboxEntry]:
    """Sessions this Sale has already claimed and is still chatting through live — without
    this, claiming removes a session from `list_waiting` and there is no other way back to
    it after navigating away or logging back in."""
    return _decorate(db, list_sessions_handled_by_sale(db, sale_id=user.id))


@router.post("/{session_id}/claim", response_model=LiveInboxEntry)
async def claim(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> LiveInboxEntry:
    session = claim_for_sale(db, session_id, sale_id=user.id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Khách này vừa được chuyên viên khác tiếp nhận.",
        )

    log_event("chat.handoff.claimed", session_id=session_id, sale_id=user.id, customer_id=session.customer_id)
    return _to_entry(db, session)


@router.get("/{session_id}/lead", response_model=LeadDetailResponse | None)
async def get_lead_detail(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> LeadDetailResponse | None:
    """The full scoring breakdown for the customer on this live session.

    Powers the "vì sao" panel on the chat screen itself — a richer view than the one-line
    `lead_reason` in the inbox row, with every fired signal's own point value and the LLM's
    own explanation when it has run.
    """
    session = _owned_live_session(db, session_id, user)
    customer_id = session.customer_id
    if not customer_id:
        return None
    lead = get_lead_for_customer(db, customer_id)
    if lead is None or lead.scored_at is None:
        return None

    user_row = get_user_by_id(db, customer_id)
    weights = (lead.signals or {}).get("weights") or {}
    signals = [
        LeadSignalDetail(label=_SIGNAL_LABELS[name], points=points)
        for name, points in sorted(weights.items(), key=lambda item: item[1], reverse=True)
        if name in _SIGNAL_LABELS
    ]

    flags = (lead.signals or {}).get("flags") or {}
    has_phone = bool(user_row is not None and user_row.phone)
    profile = memory_service.load_profile(memory_service.customer_key(customer_id))

    return LeadDetailResponse(
        customer_label=_customer_label(user_row, session),
        customer_name=user_row.full_name if user_row else None,
        customer_phone=user_row.phone if user_row else None,
        next_action=lead_scoring_service.suggest_next_action(
            LeadTier(lead.tier),
            has_phone=has_phone,
            has_budget=bool(flags.get("stated_budget")),
            wants_human=bool(flags.get("wants_human")),
            turn_count=lead.turn_count,
        ),
        budgets=profile.budgets,
        unit_types=profile.unit_types,
        projects=profile.projects,
        lead_tier=LeadTier(lead.tier),
        lead_score=lead.score,
        rule_score=lead.rule_score,
        soft_score=lead.soft_score,
        urgency=LeadUrgency(lead.urgency) if lead.urgency else None,
        purpose=LeadPurpose(lead.purpose) if lead.purpose else None,
        confidence=lead.confidence,
        detection_method=lead.detection_method,
        turn_count=lead.turn_count,
        scored_at=lead.scored_at,
        signals=signals,
        llm_reason=(lead.signals or {}).get("llm_reason"),
    )


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
async def get_live_messages(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> list[Message]:
    """Only what was said on this LIVE row — the customer's AI-era conversation lives in a
    separate `channel=AI` session the Sale cannot open (see `_owned_live_session`). Use
    `get_ai_history` for a deliberate, read-only look at that prior conversation."""
    _owned_live_session(db, session_id, user)
    return list_messages_for_session(db, session_id)


@router.get("/{session_id}/ai-history", response_model=list[MessageResponse])
async def get_ai_history(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> list[Message]:
    """Read-only look at the customer's AI-era conversation, so a Sale isn't forced to make
    the customer repeat themselves — a deliberate, explicit crossing of the privacy boundary
    `_owned_live_session` otherwise enforces (see that function and `SessionChannel`'s
    docstring), rather than the old behaviour of silently merging it into the live transcript.
    """
    session = _owned_live_session(db, session_id, user)
    ai_session = get_latest_customer_session(db, session.customer_id) if session.customer_id else None
    return list_messages_for_session(db, ai_session.id) if ai_session else []


@router.get("/{session_id}/customer-summary", response_model=CustomerConversationSummaryResponse)
async def get_customer_summary(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> CustomerConversationSummaryResponse:
    """Return the last saved handoff brief without spending an LLM call.

    The authorization check resolves only the LIVE row currently owned by this Sale. The
    service may aggregate the matching AI row internally, but raw AI messages never cross
    this endpoint.
    """

    session = _owned_live_session(db, session_id, user)
    if session.customer_id is None:  # defensive invariant; _owned_live_session rejects this
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phiên live không gắn với khách hàng.")
    summary = customer_summary_service.get_summary_response(db, session.customer_id)
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Khách hàng chưa có bản tóm tắt.")
    return summary


@router.post("/{session_id}/customer-summary/refresh", response_model=CustomerConversationSummaryResponse)
async def refresh_customer_summary(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> CustomerConversationSummaryResponse:
    """Update the brief from messages after its checkpoint, or return the fresh cache."""

    session = _owned_live_session(db, session_id, user)
    if session.customer_id is None:  # defensive invariant; _owned_live_session rejects this
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phiên live không gắn với khách hàng.")
    try:
        summary = customer_summary_service.refresh_summary(db, session.customer_id)
    except customer_summary_service.CustomerSummaryGenerationError as exc:
        detail = (
            "Dịch vụ AI tạm thời đã đạt giới hạn sử dụng. Bản tóm tắt cũ vẫn được giữ nguyên."
            if is_gemini_quota_error(exc)
            else "Không thể cập nhật tóm tắt lúc này. Bản tóm tắt cũ vẫn được giữ nguyên."
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc

    log_event(
        "chat.customer_summary.refreshed",
        user_id=user.id,
        username=user.username,
        session_id=session.id,
        customer_id=session.customer_id,
        newly_processed_message_count=summary.newly_processed_message_count,
        source_message_count=summary.source_message_count,
        from_cache=summary.from_cache,
    )
    return summary


@router.post("/{session_id}/reply", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def reply(
    session_id: int,
    payload: SaleLiveMessageRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> MessageResponse:
    """A Sale's own words, typed and sent directly — never touches the AI pipeline."""
    session = _owned_live_session(db, session_id, user)
    if session.status != SessionStatus.SALE_HANDLING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session is not live")

    message = create_message(db, session_id, sender=MessageSender.SALE, content=payload.content)
    log_event("chat.handoff.reply", session_id=session_id, sale_id=user.id, content_len=len(payload.content))
    return message


@router.post("/{session_id}/end", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def end(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> MessageResponse:
    """The Sale is done — hand the session back to the AI. Clears `sale_id` (see
    `return_to_bot`), so this session disappears from this Sale's "mine" list and, if the
    customer needs a human again later, any Sale can pick up the fresh handoff — not
    necessarily the same one."""
    session = _owned_live_session(db, session_id, user)
    return_to_bot(db, session)
    log_event("chat.handoff.ended_by_sale", session_id=session_id, sale_id=user.id)
    return create_message(db, session_id, sender=MessageSender.AGENT, content=_HANDOFF_ENDED_MESSAGE)


@router.post("/{session_id}/suggest", response_model=SaleSuggestResponse)
async def suggest(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> SaleSuggestResponse:
    """Co-pilot: draft a reply to the customer's latest message for the Sale to review and
    edit before sending via `/reply` — never persisted, never sent on its own. Runs at
    INTERNAL clearance since a Sale is now supervising every word before it goes out.
    """
    session = _owned_live_session(db, session_id, user)
    if session.status != SessionStatus.SALE_HANDLING:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Session is not live")

    messages = list_messages_for_session(db, session_id)
    last_customer_message = next((m for m in reversed(messages) if m.sender == MessageSender.CUSTOMER), None)
    if last_customer_message is None:
        return SaleSuggestResponse(draft="")

    ai_session = get_latest_customer_session(db, session.customer_id) if session.customer_id else None
    prior = list_messages_for_session(db, ai_session.id) if ai_session else []

    history = history_for_pipeline([*prior, *(m for m in messages if m is not last_customer_message)])
    result = agent_pipeline.run_pipeline(
        last_customer_message.content,
        project_id=session.project_id,
        db=db,
        clearance=DocumentVisibility.INTERNAL,
        history=history,
        session_id=session_id,
    )
    return SaleSuggestResponse(draft=result.draft_answer, requires_hitl=result.requires_hitl)
