from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.core.audit import log_event, truncate
from backend.core.config import settings
from backend.core.deps import require_role
from backend.core.enums import MessageSender, SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.models.audit_log import AuditLog
from backend.models.chat_session import ChatSession
from backend.models.message import Message
from backend.models.user import User
from backend.repositories.user import create_user
from backend.schemas.admin_dashboard import (
    ManagedLiveSessionResponse,
    SaleAccountCreate,
    SaleActiveUpdate,
    SalePresence,
    SaleReassignRequest,
    SalesBoardResponse,
    SalesBoardSummary,
    SaleStatusResponse,
)
from backend.utils.time import utcnow

router = APIRouter(
    prefix="/admin/sales",
    tags=["Admin Sales"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


@router.post("", response_model=SaleStatusResponse, status_code=status.HTTP_201_CREATED)
async def create_sale_account(
    payload: SaleAccountCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> SaleStatusResponse:
    """Create a Sale-only account without exposing role selection to the client."""
    username = payload.username.strip()
    email = str(payload.email).strip().lower()

    username_taken = db.query(User.id).filter(func.lower(User.username) == username.lower()).first()
    if username_taken is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Tên đăng nhập đã được sử dụng.")

    email_taken = db.query(User.id).filter(func.lower(User.email) == email).first()
    if email_taken is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email đã được sử dụng.")

    try:
        sale = create_user(
            db,
            username=username,
            email=email,
            password=payload.password,
            role=UserRole.SALE,
            is_active=payload.is_active,
        )
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tên đăng nhập hoặc email đã được sử dụng.",
        ) from exc

    log_event(
        "admin.sale.created",
        user_id=admin.id,
        username=admin.username,
        sale_id=sale.id,
        sale_username=sale.username,
        is_active=sale.is_active,
    )
    return SaleStatusResponse(
        id=sale.id,
        username=sale.username,
        email=sale.email,
        is_active=sale.is_active,
        presence="offline",
        active_chat_sessions=0,
        handled_sessions=0,
    )


def _is_customer_session(session: ChatSession) -> bool:
    return session.customer_id is not None or session.visitor_token is not None


def _customer_label(session: ChatSession, customers: dict[int, User]) -> str:
    customer = customers.get(session.customer_id) if session.customer_id is not None else None
    if customer is not None:
        return customer.email
    if session.customer_name:
        return session.customer_name
    return f"Khách ẩn danh #{session.id}"


@router.get("", response_model=SalesBoardResponse)
async def get_sales_board(
    days: int = Query(default=30, ge=7, le=90),
    db: Session = Depends(get_db),
) -> SalesBoardResponse:
    """Operational board for Sale accounts and customer handoff sessions.

    Presence is intentionally described as an estimate: this codebase has polling rather
    than WebSockets/presence heartbeats. A Sale is busy while handling a customer, online
    after any audited action in the configured window, and offline otherwise.
    """
    now = utcnow()
    cutoff = now - timedelta(days=days)
    online_cutoff = now - timedelta(minutes=settings.admin_presence_window_minutes)

    sales = (
        db.query(User)
        .filter(User.role == UserRole.SALE, ~User.username.like("e2e_sale_%"))
        .order_by(User.username.asc())
        .all()
    )
    sale_by_id = {sale.id: sale for sale in sales}

    all_customer_sessions = [session for session in db.query(ChatSession).all() if _is_customer_session(session)]
    live_sessions = [
        session
        for session in all_customer_sessions
        if session.status in {SessionStatus.WAITING_SALE, SessionStatus.SALE_HANDLING}
    ]

    session_ids = [session.id for session in all_customer_sessions]
    messages = (
        db.query(Message)
        .filter(Message.session_id.in_(session_ids))
        .order_by(Message.created_at.desc(), Message.id.desc())
        .all()
        if session_ids
        else []
    )
    latest_message: dict[int, Message] = {}
    sale_replied_session_ids: set[int] = set()
    latest_message_by_sale: dict[int, datetime] = {}
    session_by_id = {session.id: session for session in all_customer_sessions}
    for message in messages:
        if message.session_id is None:
            continue
        latest_message.setdefault(message.session_id, message)
        session = session_by_id.get(message.session_id)
        if session is None or session.sale_id is None:
            continue
        previous = latest_message_by_sale.get(session.sale_id)
        if previous is None or message.created_at > previous:
            latest_message_by_sale[session.sale_id] = message.created_at
        if message.sender == MessageSender.SALE:
            sale_replied_session_ids.add(message.session_id)

    audit_rows = (
        db.query(AuditLog).filter(AuditLog.user_id.in_(list(sale_by_id))).order_by(AuditLog.created_at.desc()).all()
        if sale_by_id
        else []
    )
    latest_audit_by_sale: dict[int, datetime] = {}
    for row in audit_rows:
        if row.user_id is not None:
            latest_audit_by_sale.setdefault(row.user_id, row.created_at)

    active_counts: dict[int, int] = defaultdict(int)
    handled_counts: dict[int, int] = defaultdict(int)
    interacted_counts: dict[int, int] = defaultdict(int)
    for session in all_customer_sessions:
        if session.sale_id is None:
            continue
        if session.status == SessionStatus.SALE_HANDLING:
            active_counts[session.sale_id] += 1
        if session.created_at >= cutoff:
            handled_counts[session.sale_id] += 1
            if session.id in sale_replied_session_ids:
                interacted_counts[session.sale_id] += 1

    sale_rows: list[SaleStatusResponse] = []
    for sale in sales:
        candidates = [latest_message_by_sale.get(sale.id), latest_audit_by_sale.get(sale.id)]
        last_activity = max((value for value in candidates if value is not None), default=None)
        presence: SalePresence
        if not sale.is_active:
            presence = "offline"
        elif active_counts[sale.id] > 0:
            presence = "busy"
        elif last_activity is not None and last_activity >= online_cutoff:
            presence = "online"
        else:
            presence = "offline"

        handled = handled_counts[sale.id]
        sale_rows.append(
            SaleStatusResponse(
                id=sale.id,
                username=sale.username,
                email=sale.email,
                is_active=sale.is_active,
                presence=presence,
                active_chat_sessions=active_counts[sale.id],
                handled_sessions=handled,
                interaction_rate=round(interacted_counts[sale.id] / handled * 100, 1) if handled else None,
                conversion_rate=None,
                last_activity_at=last_activity,
            )
        )

    customer_ids = {session.customer_id for session in live_sessions if session.customer_id is not None}
    customers = (
        {user.id: user for user in db.query(User).filter(User.id.in_(customer_ids)).all()} if customer_ids else {}
    )
    live_rows = []
    for session in sorted(
        live_sessions,
        key=lambda row: row.handoff_requested_at or row.created_at,
    ):
        last_message = latest_message.get(session.id)
        live_rows.append(
            ManagedLiveSessionResponse(
                session_id=session.id,
                customer_label=_customer_label(session, customers),
                current_sale_id=session.sale_id,
                current_sale_name=sale_by_id[session.sale_id].username if session.sale_id in sale_by_id else None,
                status=str(session.status),
                waiting_since=session.handoff_requested_at,
                project_id=session.project_id,
                last_message_preview=(truncate(last_message.content, 90) or "") if last_message else "",
            )
        )

    return SalesBoardResponse(
        generated_at=now,
        presence_window_minutes=settings.admin_presence_window_minutes,
        summary=SalesBoardSummary(
            total_sales=len(sales),
            active_accounts=sum(sale.is_active for sale in sales),
            online_sales=sum(row.presence == "online" for row in sale_rows),
            busy_sales=sum(row.presence == "busy" for row in sale_rows),
            waiting_customers=sum(session.status == SessionStatus.WAITING_SALE for session in live_sessions),
            live_customers=sum(session.status == SessionStatus.SALE_HANDLING for session in live_sessions),
        ),
        sales=sale_rows,
        live_sessions=live_rows,
    )


@router.patch("/{sale_id}/active", response_model=SaleStatusResponse)
async def update_sale_active_state(
    sale_id: int,
    payload: SaleActiveUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> SaleStatusResponse:
    sale = db.query(User).filter(User.id == sale_id, User.role == UserRole.SALE).with_for_update().first()
    if sale is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy tài khoản Sale.")

    active_chats = (
        db.query(ChatSession)
        .filter(
            ChatSession.sale_id == sale_id,
            ChatSession.status == SessionStatus.SALE_HANDLING,
        )
        .count()
    )
    if not payload.is_active and active_chats:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Hãy chuyển các phiên khách đang xử lý sang Sale khác trước khi vô hiệu hóa tài khoản.",
        )

    sale.is_active = payload.is_active
    db.commit()
    db.refresh(sale)
    log_event(
        "admin.sale.active_changed",
        user_id=admin.id,
        username=admin.username,
        sale_id=sale.id,
        is_active=sale.is_active,
    )
    return SaleStatusResponse(
        id=sale.id,
        username=sale.username,
        email=sale.email,
        is_active=sale.is_active,
        presence="offline",
        active_chat_sessions=0,
        handled_sessions=0,
    )


@router.post("/reassign", response_model=ManagedLiveSessionResponse)
async def reassign_customer(
    payload: SaleReassignRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> ManagedLiveSessionResponse:
    session = db.query(ChatSession).filter(ChatSession.id == payload.session_id).with_for_update().first()
    if session is None or not _is_customer_session(session):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy phiên khách hàng.")
    if session.status not in {SessionStatus.WAITING_SALE, SessionStatus.SALE_HANDLING}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Phiên này hiện không cần Sale xử lý.")

    target = db.query(User).filter(User.id == payload.to_sale_id, User.role == UserRole.SALE).with_for_update().first()
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy Sale nhận khách.")
    if not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Không thể giao khách cho Sale đã bị vô hiệu hóa."
        )

    previous_sale_id = session.sale_id
    session.sale_id = target.id
    session.status = SessionStatus.SALE_HANDLING
    session.handoff_requested_at = None
    db.commit()
    db.refresh(session)
    log_event(
        "admin.sale.reassigned",
        user_id=admin.id,
        username=admin.username,
        session_id=session.id,
        from_sale_id=previous_sale_id,
        to_sale_id=target.id,
    )

    customer = db.get(User, session.customer_id) if session.customer_id is not None else None
    message = (
        db.query(Message)
        .filter(Message.session_id == session.id)
        .order_by(Message.created_at.desc(), Message.id.desc())
        .first()
    )
    return ManagedLiveSessionResponse(
        session_id=session.id,
        customer_label=customer.email if customer else _customer_label(session, {}),
        current_sale_id=target.id,
        current_sale_name=target.username,
        status=str(session.status),
        waiting_since=None,
        project_id=session.project_id,
        last_message_preview=(truncate(message.content, 90) or "") if message else "",
    )
