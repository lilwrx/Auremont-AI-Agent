from typing import cast

from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from backend.core.enums import SessionChannel, SessionStatus
from backend.models.chat_session import ChatSession
from backend.models.message import Message
from backend.models.user import User
from backend.schemas.chat_session import ChatSessionCreate
from backend.schemas.customer import CustomerChatSessionCreate
from backend.utils.time import utcnow


def create_session(db: Session, sale_id: int, schema: ChatSessionCreate) -> ChatSession:
    session = ChatSession(
        sale_id=sale_id,
        title=schema.title,
        customer_name=schema.customer_name,
        project_id=schema.project_id,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def list_sessions_for_sale(db: Session, sale_id: int) -> list[ChatSession]:
    """A Sale's own AI-consult sessions only.

    `customer_id IS NULL` excludes a customer session this Sale has claimed via
    `claim_for_sale` — that row also carries this Sale's `sale_id`, but it belongs in the
    live-inbox flow (`routers/sale_live.py`), not mixed into the self-consult sidebar.
    """
    return (
        db.query(ChatSession)
        .filter(ChatSession.sale_id == sale_id, ChatSession.customer_id.is_(None))
        .order_by(ChatSession.created_at.desc())
        .all()
    )


def get_session(db: Session, session_id: int) -> ChatSession | None:
    return db.query(ChatSession).filter(ChatSession.id == session_id).first()


def set_title_if_empty(db: Session, session: ChatSession, title: str) -> ChatSession:
    """Auto-titles the session from the Sale's first question — avoids a session
    list full of indistinguishable "Session: Khách #N" entries once there are many."""
    if session.title:
        return session
    session.title = title[:40] + ("…" if len(title) > 40 else "")
    db.commit()
    db.refresh(session)
    return session


def delete_session(db: Session, session_id: int) -> None:
    session = get_session(db, session_id)
    if session is None:
        return
    db.delete(session)
    db.commit()


def create_anonymous_session(db: Session, visitor_token: str, project_id: str | None = None) -> ChatSession:
    """A public-chat session with no account behind it yet — see ChatSession's docstring
    for the sale_id/customer_id/visitor_token ownership invariant."""
    session = ChatSession(visitor_token=visitor_token, project_id=project_id, channel=SessionChannel.AI)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def create_customer_session(db: Session, customer_id: int, schema: CustomerChatSessionCreate) -> ChatSession:
    """Create a row directly.

    Kept for fixtures/import jobs that intentionally construct a particular state. Public
    API code must use `get_or_create_customer_session`, which enforces one continuing
    session per customer.
    """
    session = ChatSession(
        customer_id=customer_id, title=schema.title, project_id=schema.project_id, channel=SessionChannel.AI
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_latest_customer_session(db: Session, customer_id: int) -> ChatSession | None:
    """The customer's AI conversation. Scoped to `channel=AI` on purpose: their live-Sale
    thread is a separate row, and the customer-facing AI page must never resume into it."""
    return (
        db.query(ChatSession)
        .filter(ChatSession.customer_id == customer_id, ChatSession.channel == SessionChannel.AI)
        .order_by(ChatSession.created_at.desc(), ChatSession.id.desc())
        .first()
    )


def get_live_session_for_customer(db: Session, customer_id: int) -> ChatSession | None:
    """The customer's live-Sale conversation, if one exists — the only row a Sale is ever
    handed for this customer."""
    return (
        db.query(ChatSession)
        .filter(ChatSession.customer_id == customer_id, ChatSession.channel == SessionChannel.LIVE)
        .order_by(ChatSession.created_at.desc(), ChatSession.id.desc())
        .first()
    )


def get_or_create_live_session(db: Session, customer_id: int, project_id: str | None = None) -> ChatSession:
    """The customer's live-Sale conversation, created empty on first request.

    Locks the owner row for the same reason `get_or_create_customer_session` does: two tabs
    both hitting "gặp chuyên viên" at once must not create two queue entries.
    """
    db.query(User).filter(User.id == customer_id).with_for_update().one()
    existing = get_live_session_for_customer(db, customer_id)
    if existing is not None:
        return existing
    session = ChatSession(customer_id=customer_id, channel=SessionChannel.LIVE, project_id=project_id)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_or_create_customer_session(db: Session, customer_id: int, schema: CustomerChatSessionCreate) -> ChatSession:
    """The customer's one durable conversation, safe against concurrent first sends.

    Locking the owner row serialises two browser tabs that both reach the first-message
    path at once. Without it, both can observe "no session" and create separate rows,
    splitting short-term history despite an idempotent-looking API.
    """
    db.query(User).filter(User.id == customer_id).with_for_update().one()
    existing = get_latest_customer_session(db, customer_id)
    if existing is not None:
        return existing
    return create_customer_session(db, customer_id, schema)


def list_sessions_for_customer(db: Session, customer_id: int) -> list[ChatSession]:
    session = get_latest_customer_session(db, customer_id)
    return [session] if session is not None else []


def claim_or_merge_anonymous_session(db: Session, anonymous: ChatSession, customer_id: int) -> ChatSession:
    """Attach an anonymous conversation to the account's one durable session.

    A newly registered account has no existing row, so ownership simply transfers. An
    existing customer may log in after chatting anonymously in another browser; in that
    case the anonymous messages are moved into their canonical session before the
    temporary row is removed. No transcript is discarded and every later turn sees one
    continuous short-term history.
    """
    db.query(User).filter(User.id == customer_id).with_for_update().one()
    canonical = get_latest_customer_session(db, customer_id)
    if canonical is None:
        anonymous.customer_id = customer_id
        anonymous.visitor_token = None
        db.commit()
        db.refresh(anonymous)
        return anonymous

    db.query(Message).filter(Message.session_id == anonymous.id).update(
        {Message.session_id: canonical.id}, synchronize_session=False
    )
    if not canonical.title and anonymous.title:
        canonical.title = anonymous.title
    if not canonical.project_id and anonymous.project_id:
        canonical.project_id = anonymous.project_id
    db.delete(anonymous)
    db.commit()
    db.refresh(canonical)
    return canonical


def enter_waiting_queue(db: Session, session: ChatSession) -> ChatSession:
    """Flip a customer session to WAITING_SALE and stamp `handoff_requested_at`.

    That timestamp — not `created_at` — is what the live-inbox queue's "waiting since" is
    measured from: a session can exist for a long time (chatting with the AI) before it ever
    needs a human, so `created_at` alone would show a wildly inflated wait time.
    """
    session.status = SessionStatus.WAITING_SALE
    session.handoff_requested_at = utcnow()
    db.commit()
    db.refresh(session)
    return session


def return_to_bot(db: Session, session: ChatSession) -> ChatSession:
    """End a live handoff (WAITING_SALE or SALE_HANDLING) and give the session back to the
    AI. Clears `sale_id` and `handoff_requested_at` too, not just `status` — this restores
    the exact "customer_id only" shape a never-claimed customer session has, so a later
    handoff starts clean (fresh queue position, any Sale can pick it up) rather than leaving
    a stale claim/timestamp behind.
    """
    session.status = SessionStatus.BOT_HANDLING
    session.sale_id = None
    session.handoff_requested_at = None
    db.commit()
    db.refresh(session)
    return session


def list_waiting_sessions(db: Session) -> list[ChatSession]:
    """Sessions a customer has been routed to a live Sale for — the live-inbox queue, oldest
    wait first (FIFO)."""
    return (
        db.query(ChatSession)
        .filter(ChatSession.status == SessionStatus.WAITING_SALE, ChatSession.channel == SessionChannel.LIVE)
        .order_by(ChatSession.handoff_requested_at.asc())
        .all()
    )


def list_sessions_handled_by_sale(db: Session, sale_id: int) -> list[ChatSession]:
    """Sessions this Sale currently owns via a live handoff (already claimed, still live) —
    the "your ongoing chats" list, distinct from `list_waiting_sessions` (not yet claimed by
    anyone). Without this, a Sale who navigates away from `LiveChatPage` (or logs back in
    later) has no way back to a customer they already claimed — claiming removes the session
    from the waiting queue, so it would otherwise just vanish from their view entirely.
    """
    return (
        db.query(ChatSession)
        .filter(
            ChatSession.sale_id == sale_id,
            ChatSession.status == SessionStatus.SALE_HANDLING,
            ChatSession.channel == SessionChannel.LIVE,
        )
        .order_by(ChatSession.created_at.desc())
        .all()
    )


def claim_for_sale(db: Session, session_id: int, sale_id: int) -> ChatSession | None:
    """Atomically hand a waiting session to the calling Sale.

    The UPDATE's WHERE clause re-checks `status == WAITING_SALE` at the database level, so
    two Sales claiming the same session at nearly the same moment can't both succeed — only
    the first UPDATE actually matches a row (`rowcount == 1`); the second finds nothing to
    update and this returns `None`, which the router turns into a 409 telling that Sale
    someone else got there first.
    """
    result = cast(
        CursorResult,
        db.execute(
            update(ChatSession)
            .where(
                ChatSession.id == session_id,
                ChatSession.status == SessionStatus.WAITING_SALE,
                ChatSession.channel == SessionChannel.LIVE,
            )
            .values(sale_id=sale_id, status=SessionStatus.SALE_HANDLING)
        ),
    )
    db.commit()
    if result.rowcount == 0:
        return None
    return get_session(db, session_id)
