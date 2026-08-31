import secrets
import time
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.ai.intent import needs_human_handoff, wants_human_agent
from backend.core.audit import log_event, redact_and_truncate
from backend.core.config import settings
from backend.core.deps import get_optional_current_user, require_role
from backend.core.enums import (
    DocumentVisibility,
    MessageEmotion,
    MessageSender,
    SessionChannel,
    SessionStatus,
    UserRole,
)
from backend.core.mysql_client import get_db
from backend.core.rate_limit import anonymous_rate_limit
from backend.core.security import create_access_token, create_refresh_token
from backend.models.chat_session import ChatSession
from backend.models.message import Message
from backend.models.user import User
from backend.repositories.chat_session import (
    claim_or_merge_anonymous_session,
    create_anonymous_session,
    delete_session,
    enter_waiting_queue,
    get_live_session_for_customer,
    get_or_create_customer_session,
    get_or_create_live_session,
    get_session,
    list_sessions_for_customer,
    return_to_bot,
    set_title_if_empty,
)
from backend.repositories.feedback import delete_feedback_for_session
from backend.repositories.hitl_log import delete_hitl_logs_for_session
from backend.repositories.lead import claim_anonymous_lead, get_or_create_lead, reset_lead_score
from backend.repositories.message import (
    create_message,
    delete_messages_for_session,
    history_for_pipeline,
    list_messages_for_session,
)
from backend.repositories.user import create_user, get_user_by_email
from backend.schemas.customer import (
    AnonymousSessionClaimRequest,
    AnonymousSessionResponse,
    CustomerAskRequest,
    CustomerAskResponse,
    CustomerChatSessionCreate,
    CustomerChatSessionResponse,
    CustomerRegisterRequest,
)
from backend.schemas.message import MessageResponse
from backend.schemas.user import TokenResponse, UserResponse
from backend.services import agent_pipeline, lead_service, memory_service, search_criteria
from backend.utils.time import utcnow

router = APIRouter(prefix="/customer", tags=["Customer Chat"])

_TURN_LIMIT_MESSAGE = (
    "Cảm ơn bạn đã trò chuyện cùng Auremont! Để mình lưu lại đoạn chat này và tư vấn sâu hơn, "
    "bạn vui lòng đăng ký/đăng nhập tài khoản nhé."
)
_DAILY_LIMIT_ANONYMOUS_MESSAGE = (
    "Bạn đã dùng hết lượt hỏi miễn phí hôm nay. Đăng ký tài khoản để được hỏi nhiều hơn mỗi ngày "
    "và lưu lại toàn bộ lịch sử tư vấn nhé!"
)
_DAILY_LIMIT_REGISTERED_MESSAGE = (
    "Bạn đã dùng hết lượt hỏi AI hôm nay. Lượt mới sẽ được làm mới vào ngày mai. "
    "Nếu cần gấp, bạn nhắn 'gặp tư vấn viên' để được chuyên viên hỗ trợ trực tiếp nhé."
)
_HANDOFF_NOTICE_MESSAGE = (
    "Dạ em xin phép kết nối anh/chị với "
    "chuyên viên tư vấn ngay bây giờ ạ. Chuyên viên sẽ đọc lại toàn bộ nội dung mình vừa trao "
    "đổi nên anh/chị không cần nhắc lại từ đầu."
)
_HANDOFF_DIRECT_REQUEST_MESSAGE = (
    "Dạ vâng, em xin phép kết nối anh/chị với chuyên viên tư vấn ngay bây giờ ạ. Chuyên viên "
    "sẽ đọc lại toàn bộ nội dung mình vừa trao đổi nên anh/chị không cần nhắc lại từ đầu."
)
_RETURN_TO_AI_MESSAGE = (
    "Bạn đã quay lại chat với Auremont AI. Bạn có thể tiếp tục hỏi mình bất cứ điều gì về dự án nhé!"
)


def _resolve_customer_asker(
    db: Session,
    session: ChatSession | None,
    user: User | None,
    visitor_token: str | None,
) -> ChatSession:
    """404 unless the caller genuinely owns this session — same "don't reveal which ids
    exist" posture as `sale_chat._owned_session`.

    A session is owned either by a logged-in CUSTOMER whose id matches `session.customer_id`,
    or — while still anonymous — by whoever holds the matching `visitor_token` (there is no
    account to check identity against yet).
    """
    not_found = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    if session is None:
        raise not_found

    if session.customer_id is not None:
        if user is None or user.role != UserRole.CUSTOMER or session.customer_id != user.id:
            raise not_found
        return session

    if session.visitor_token is None or session.visitor_token != visitor_token:
        raise not_found
    return session


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register_customer(
    payload: CustomerRegisterRequest,
    db: Session = Depends(get_db),
    _: None = Depends(anonymous_rate_limit),
) -> TokenResponse:
    """Create a CUSTOMER account and, if the visitor was chatting anonymously, claim their
    in-progress session so the conversation continues without losing history."""
    if get_user_by_email(db, payload.email) is not None:
        log_event("customer.register.failure", reason="email_taken")
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    if settings.lead_require_phone_on_register and not payload.phone:
        log_event("customer.register.failure", reason="phone_missing")
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Vui lòng nhập số điện thoại")

    user = create_user(
        db,
        username=payload.email,
        email=payload.email,
        password=payload.password,
        role=UserRole.CUSTOMER,
        full_name=payload.full_name,
        phone=payload.phone,
    )

    if payload.session_id is not None and payload.visitor_token is not None:
        session = get_session(db, payload.session_id)
        if session is not None and session.customer_id is None and session.visitor_token == payload.visitor_token:
            canonical = claim_or_merge_anonymous_session(db, session, user.id)
            _remember_customer_history(db, canonical, user.id)
            lead_service.rescore_after_claim(
                db, claim_anonymous_lead(db, visitor_token=payload.visitor_token, customer_id=user.id), user
            )

    log_event(
        "customer.register.success",
        username=user.username,
        user_id=user.id,
        phone_captured=user.phone is not None,
    )
    return TokenResponse(
        access_token=create_access_token(subject=user.username, role=user.role),
        refresh_token=create_refresh_token(subject=user.username),
        user=UserResponse.model_validate(user),
    )


@router.post("/sessions/anonymous", response_model=AnonymousSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_anonymous_chat_session(
    db: Session = Depends(get_db),
    _: None = Depends(anonymous_rate_limit),
) -> AnonymousSessionResponse:
    """Start a session for a visitor with no account — the token is opaque and
    server-generated, never something the client can forge or guess."""
    visitor_token = secrets.token_urlsafe(32)
    session = create_anonymous_session(db, visitor_token=visitor_token)
    return AnonymousSessionResponse(session_id=session.id, visitor_token=visitor_token)


@router.post("/sessions", response_model=CustomerChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_customer_chat_session(
    payload: CustomerChatSessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.CUSTOMER)),
) -> CustomerChatSessionResponse:
    return get_or_create_customer_session(db, customer_id=user.id, schema=payload)


@router.post(
    "/sessions/claim-anonymous",
    response_model=CustomerChatSessionResponse,
)
async def claim_anonymous_chat_session(
    payload: AnonymousSessionClaimRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.CUSTOMER)),
) -> CustomerChatSessionResponse:
    """Continue an anonymous transcript after logging into an existing account.

    Registration already transfers the temporary session. Login needs this explicit
    authenticated step because the generic `/auth/login` endpoint cannot safely accept an
    anonymous ownership token. If the account already has a session, both transcripts are
    merged into that canonical row.
    """
    anonymous = get_session(db, payload.session_id)
    if anonymous is None or anonymous.customer_id is not None or anonymous.visitor_token != payload.visitor_token:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    canonical = claim_or_merge_anonymous_session(db, anonymous, user.id)
    _remember_customer_history(db, canonical, user.id)
    lead_service.rescore_after_claim(
        db, claim_anonymous_lead(db, visitor_token=payload.visitor_token, customer_id=user.id), user
    )
    return canonical


@router.get("/sessions", response_model=list[CustomerChatSessionResponse])
async def list_customer_chat_sessions(
    db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.CUSTOMER))
) -> list[ChatSession]:
    return list_sessions_for_customer(db, customer_id=user.id)


@router.get("/sessions/live", response_model=CustomerChatSessionResponse | None)
async def get_my_live_session(
    db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.CUSTOMER))
) -> ChatSession | None:
    """The customer's live-Sale conversation, or null if they have never requested one.

    Declared before `/sessions/{session_id}` so the literal path wins over the int
    converter. The customer chat page polls this to know when a Sale has picked them up.
    """
    return get_live_session_for_customer(db, user.id)


@router.get("/sessions/{session_id}", response_model=CustomerChatSessionResponse)
async def get_customer_chat_session(
    session_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
    x_visitor_token: str | None = Header(default=None, alias="X-Visitor-Token"),
) -> CustomerChatSessionResponse:
    """Session metadata, chiefly `status` — the frontend polls this once a handoff is under
    way (WAITING_SALE/SALE_HANDLING) to know when to switch to live-chat rendering, since the
    ask endpoint stops returning a reply the moment a Sale is involved."""
    session = get_session(db, session_id)
    return _resolve_customer_asker(db, session, user, x_visitor_token)


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
async def list_customer_session_messages(
    session_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
    x_visitor_token: str | None = Header(default=None, alias="X-Visitor-Token"),
) -> list[Message]:
    session = get_session(db, session_id)
    session = _resolve_customer_asker(db, session, user, x_visitor_token)
    return list_messages_for_session(db, session_id)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=CustomerAskResponse | None,
    status_code=status.HTTP_201_CREATED,
)
async def ask_in_customer_session(
    session_id: int,
    payload: CustomerAskRequest,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
    x_visitor_token: str | None = Header(default=None, alias="X-Visitor-Token"),
    _: None = Depends(anonymous_rate_limit),
) -> CustomerAskResponse | None:
    """Public/customer counterpart to `sale_chat.ask_in_session` — always retrieves at
    PUBLIC clearance (see agent_pipeline.run_pipeline). There is no HITL confirm-before-send
    step here because there is no second human to perform it: the customer IS the one reading
    the answer, and nobody signs off on a commitment made to themselves. A price/commitment
    answer is therefore withheld rather than confirmed — anonymous visitors into the
    registration funnel, logged-in customers to a real Sale — which is what keeps every
    customer-visible message `requires_hitl=False`.

    Returns `None` once a live Sale is involved (WAITING_SALE/SALE_HANDLING): the message is
    still persisted, but the AI must stay completely silent from that point on so it never
    talks over the Sale. The frontend polls `GET /customer/sessions/{id}/messages` to pick up
    the Sale's reply instead of expecting one back from this call.
    """
    session = get_session(db, session_id)
    session = _resolve_customer_asker(db, session, user, x_visitor_token)
    set_title_if_empty(db, session, payload.content)

    history = history_for_pipeline(list_messages_for_session(db, session_id))

    memory_key: str | None = None
    memory_profile = ""
    if session.customer_id is not None:
        memory_key = memory_service.customer_key(session.customer_id)
        memory_profile = memory_service.format_profile(memory_service.load_profile(memory_key))

    create_message(db, session_id, sender=MessageSender.CUSTOMER, content=payload.content)
    if memory_key is not None:
        memory_service.remember(memory_key, payload.content, session.project_id, db=db)

    lead_service.rescore_for_turn(db, session, payload.content)

    if session.status != SessionStatus.BOT_HANDLING:
        log_event(
            "customer.query",
            session_id=session_id,
            customer_id=session.customer_id,
            status=session.status,
            query_len=len(payload.content),
        )
        return None

    is_anonymous = session.customer_id is None
    gate: Literal["turn_limit", "daily_limit", "closing_intent", "human_request"] | None = None
    used_cache = False
    duration_ms = 0.0
    new_status = SessionStatus(session.status)
    emotion: MessageEmotion | None = MessageEmotion.RESPECTFUL
    quick_replies: list[str] = []
    listings: list[dict] = []
    suggested_questions: list[str] = []
    images: list[dict] = []

    daily_used = _consume_daily_question(db, session)
    over_daily_budget = daily_used > _daily_limit_for(session)

    if is_anonymous and _anonymous_turn_count(db, session_id) >= settings.customer_anonymous_turn_limit:
        gate = "turn_limit"
        answer_text = _TURN_LIMIT_MESSAGE
        verifier_score, requires_hitl, faithfulness, answer_relevancy = 0.0, False, None, None
    elif over_daily_budget:
        gate = "daily_limit"
        answer_text = _DAILY_LIMIT_ANONYMOUS_MESSAGE if is_anonymous else _DAILY_LIMIT_REGISTERED_MESSAGE
        verifier_score, requires_hitl, faithfulness, answer_relevancy = 0.0, False, None, None
    elif not is_anonymous and needs_human_handoff(payload.content):
        if session.customer_id is None:
            raise RuntimeError("An authenticated customer session has no customer id.")
        live = get_or_create_live_session(db, session.customer_id, project_id=session.project_id)
        new_status = SessionStatus.WAITING_SALE
        if live.status == SessionStatus.BOT_HANDLING:
            enter_waiting_queue(db, live)
        answer_text = _HANDOFF_DIRECT_REQUEST_MESSAGE if wants_human_agent(payload.content) else _HANDOFF_NOTICE_MESSAGE
        verifier_score, requires_hitl, faithfulness, answer_relevancy = 0.0, False, None, None
    else:
        started = time.perf_counter()
        result = agent_pipeline.run_pipeline(
            payload.content,
            project_id=session.project_id,
            db=db,
            clearance=DocumentVisibility.PUBLIC,
            history=history,
            memory_profile=memory_profile,
            session_id=session_id,
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        used_cache = result.used_cache

        if result.requires_hitl:
            answer_text = result.draft_answer
            verifier_score = result.verifier_score
            faithfulness = result.faithfulness
            answer_relevancy = result.answer_relevancy
            requires_hitl = False
            emotion = MessageEmotion(result.emotion) if result.emotion else emotion
            quick_replies = result.quick_replies
            listings = result.listings
            suggested_questions = result.suggested_questions
            images = result.images
        else:
            answer_text = result.draft_answer
            verifier_score, requires_hitl = result.verifier_score, False
            faithfulness, answer_relevancy = result.faithfulness, result.answer_relevancy
            emotion = MessageEmotion(result.emotion) if result.emotion else None
            quick_replies = result.quick_replies
            listings = result.listings
            suggested_questions = result.suggested_questions
            images = result.images

    log_event(
        "customer.query",
        session_id=session_id,
        customer_id=session.customer_id,
        is_anonymous=is_anonymous,
        gate=gate,
        status=new_status,
        verifier_score=verifier_score,
        faithfulness=faithfulness,
        answer_relevancy=answer_relevancy,
        requires_hitl=requires_hitl,
        used_cache=used_cache,
        duration_ms=duration_ms,
        query_len=len(payload.content),
        query=redact_and_truncate(payload.content) if settings.log_query_text else None,
    )

    message = create_message(
        db,
        session_id,
        sender=MessageSender.AGENT,
        content=answer_text,
        verifier_score=verifier_score,
        requires_hitl=requires_hitl,
        faithfulness=faithfulness,
        answer_relevancy=answer_relevancy,
        emotion=emotion,
        quick_replies=quick_replies,
        listings=listings,
        suggested_questions=suggested_questions,
        images=images,
    )

    response = CustomerAskResponse.model_validate(message)
    response.gate = gate
    response.status = new_status
    return response


@router.post(
    "/sessions/{session_id}/request-human",
    response_model=CustomerAskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def request_human(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.CUSTOMER)),
) -> CustomerAskResponse:
    """The "Gặp chuyên viên tư vấn" button — logged-in customers only, no dual-auth: an
    anonymous visitor never sees this button (see `wants_human_agent` handling in
    `ask_in_customer_session` for their equivalent, which routes into the registration gate
    instead of a real handoff).

    `session_id` names the customer's AI session (the page they clicked from), but the
    handoff is queued on their separate LIVE session — the only row a Sale is ever handed.
    The AI conversation stays BOT_HANDLING throughout and is never exposed to the Sale.
    """
    session = get_session(db, session_id)
    _resolve_customer_asker(db, session, user, None)

    live = get_or_create_live_session(db, user.id, project_id=session.project_id if session else None)

    if live.status == SessionStatus.BOT_HANDLING:
        enter_waiting_queue(db, live)
        message = create_message(
            db,
            live.id,
            sender=MessageSender.AGENT,
            content=_HANDOFF_DIRECT_REQUEST_MESSAGE,
            emotion=MessageEmotion.RESPECTFUL,
        )
        log_event("customer.handoff.requested", session_id=live.id, customer_id=user.id)
    else:
        prior_notice = next(
            (m for m in reversed(list_messages_for_session(db, live.id)) if m.sender != MessageSender.CUSTOMER),
            None,
        )
        message = prior_notice or create_message(
            db,
            live.id,
            sender=MessageSender.AGENT,
            content=_HANDOFF_DIRECT_REQUEST_MESSAGE,
            emotion=MessageEmotion.RESPECTFUL,
        )

    response = CustomerAskResponse.model_validate(message)
    response.status = SessionStatus(live.status)
    return response


@router.post(
    "/sessions/{session_id}/return-to-ai",
    response_model=CustomerAskResponse,
    status_code=status.HTTP_201_CREATED,
)
async def return_to_ai(
    session_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.CUSTOMER)),
) -> CustomerAskResponse:
    """The customer's own escape hatch out of a live handoff (waiting or already live) —
    without this, once a Sale is involved there is no way back to the AI at all. Only
    CUSTOMER-role, no dual-auth, same reasoning as `request_human`: an anonymous visitor can
    never reach WAITING_SALE/SALE_HANDLING in the first place (see `ask_in_customer_session`),
    so there is nothing to return from.
    """
    session = get_session(db, session_id)
    session = _resolve_customer_asker(db, session, user, None)

    if session.status != SessionStatus.BOT_HANDLING:
        return_to_bot(db, session)
        log_event("customer.handoff.ended_by_customer", session_id=session_id, customer_id=user.id)

    message = create_message(db, session_id, sender=MessageSender.AGENT, content=_RETURN_TO_AI_MESSAGE)
    response = CustomerAskResponse.model_validate(message)
    response.status = SessionStatus(session.status)
    return response


def _anonymous_turn_count(db: Session, session_id: int) -> int:
    return sum(1 for m in list_messages_for_session(db, session_id) if m.sender == MessageSender.CUSTOMER)


def _consume_daily_question(db: Session, session: ChatSession) -> int:
    """Charge one question against today's budget and return the new running total.

    Held on the session row rather than derived from `messages`, because "Xoá lịch sử"
    deletes the transcript and keeps the row: a message-derived count would refund the
    whole allowance on every clear.

    For a registered customer the budget is shared across their sessions, so the counter
    on their canonical AI session is the one that moves — otherwise a second conversation
    would come with a second allowance. Anonymous visitors own exactly one session
    (`visitor_token` is UNIQUE), so their own row is already the right place.

    The day boundary is midnight UTC: a visitor told "hết lượt hôm nay" can predict when
    it resets, and rolling the date forward on write means no scheduled job has to zero
    anything.
    """
    today = utcnow().date()

    counter = session
    if session.customer_id is not None:
        canonical = db.scalar(
            select(ChatSession)
            .where(ChatSession.customer_id == session.customer_id, ChatSession.channel == SessionChannel.AI)
            .order_by(ChatSession.id)
            .limit(1)
        )
        counter = canonical or session

    if counter.ai_questions_date != today:
        counter.ai_questions_date = today
        counter.ai_questions_today = 0

    counter.ai_questions_today += 1
    db.commit()
    return counter.ai_questions_today


def _daily_limit_for(session: ChatSession) -> int:
    """A registered customer's larger allowance, or the anonymous one."""
    if session.customer_id is not None:
        return settings.customer_registered_daily_limit
    return settings.customer_anonymous_daily_limit


def _remember_customer_history(db: Session, session: ChatSession, customer_id: int) -> None:
    """Seed long-term memory from turns written before an anonymous session was claimed."""
    key = memory_service.customer_key(customer_id)
    for message in list_messages_for_session(db, session.id):
        if message.sender == MessageSender.CUSTOMER:
            memory_service.remember(key, message.content, session.project_id, db=db)


def _forget_customer_context(
    session_id: int, customer_id: int | None, db: Session | None = None, visitor_token: str | None = None
) -> None:
    """Drop the context that would otherwise outlive the messages the customer just erased.

    Mostly the non-MySQL layers (Redis search criteria, long-term memory), plus one MySQL
    one: the lead score. Its signals were read off the very messages being deleted, so
    keeping the tier would leave a verdict with no evidence behind it. The lead ROW and its
    identity survive — clearing a conversation is not a request to delete an account.
    """
    search_criteria.clear(session_id)
    if customer_id is not None:
        memory_service.forget(memory_service.customer_key(customer_id))
    if db is not None:
        lead = get_or_create_lead(db, customer_id=customer_id, visitor_token=visitor_token)
        if lead is not None:
            reset_lead_score(db, lead)


@router.delete("/sessions/{session_id}/messages", status_code=status.HTTP_204_NO_CONTENT)
async def clear_customer_session_messages(
    session_id: int,
    db: Session = Depends(get_db),
    user: User | None = Depends(get_optional_current_user),
    x_visitor_token: str | None = Header(default=None, alias="X-Visitor-Token"),
) -> None:
    """Forget one customer's conversation while keeping its stable session id.

    Both ownership forms are supported: a CUSTOMER account or the anonymous browser token.
    Clearing visible rows alone is insufficient because the next answer could otherwise
    reuse Redis preferences or accumulated search criteria from the deleted conversation.
    A live handoff is also ended so a Sale cannot write into a transcript the customer has
    explicitly erased.
    """
    session = get_session(db, session_id)
    session = _resolve_customer_asker(db, session, user, x_visitor_token)
    customer_id = session.customer_id
    if session.status != SessionStatus.BOT_HANDLING:
        session = return_to_bot(db, session)
    delete_hitl_logs_for_session(db, session_id)
    delete_feedback_for_session(db, session_id)
    delete_messages_for_session(db, session_id)
    session.title = None
    db.commit()
    _forget_customer_context(session_id, customer_id, db=db, visitor_token=session.visitor_token)
    log_event(
        "customer.history.cleared",
        session_id=session_id,
        customer_id=customer_id,
        is_anonymous=customer_id is None,
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_customer_session(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.CUSTOMER))
) -> None:
    session = get_session(db, session_id)
    session = _resolve_customer_asker(db, session, user, None)
    delete_hitl_logs_for_session(db, session_id)
    delete_feedback_for_session(db, session_id)
    delete_messages_for_session(db, session_id)
    _forget_customer_context(session_id, session.customer_id, db=db, visitor_token=session.visitor_token)
    delete_session(db, session_id)
