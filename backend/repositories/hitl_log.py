from sqlalchemy.orm import Session

from backend.core.enums import HitlStatus
from backend.models.hitl_log import HitlLog
from backend.models.message import Message
from backend.utils.time import utcnow


def delete_hitl_logs_for_session(db: Session, session_id: int) -> None:
    """Drop the confirmations belonging to a conversation's messages.

    `hitl_logs.message_id` is a non-null FK with no cascade, so this has to run before the
    messages are removed. Without it, deleting any conversation that contains a confirmed
    price answer fails with an integrity error and the conversation stays in the list.
    """
    message_ids = db.query(Message.id).filter(Message.session_id == session_id).scalar_subquery()
    db.query(HitlLog).filter(HitlLog.message_id.in_(message_ids)).delete(synchronize_session=False)
    db.commit()


def get_confirmation_for_message(db: Session, message_id: int) -> HitlLog | None:
    """The confirmation recorded against a message, if a Sale has already given one.

    Confirmation state is read from here rather than from a column on the message, so a
    client cannot present an answer as approved without a matching audit row.
    """
    return (
        db.query(HitlLog)
        .filter(HitlLog.message_id == message_id, HitlLog.status == HitlStatus.CONFIRMED)
        .order_by(HitlLog.id.desc())
        .first()
    )


def confirmed_message_ids(db: Session, message_ids: list[int]) -> set[int]:
    """Which of these messages already carry a confirmation.

    Batched to keep listing a conversation to one query instead of one per message.
    """
    if not message_ids:
        return set()

    rows = (
        db.query(HitlLog.message_id)
        .filter(HitlLog.message_id.in_(message_ids), HitlLog.status == HitlStatus.CONFIRMED)
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def confirm_message(db: Session, message_id: int, sale_id: int, confirmed_content: str) -> HitlLog:
    """Record that a Sale read and approved this answer for a customer.

    Idempotent: confirming twice returns the existing row rather than inserting a second
    one. The previous implementation always inserted, so a double-click produced two audit
    rows for a single human decision and made the trail ambiguous.
    """
    existing = get_confirmation_for_message(db, message_id)
    if existing is not None:
        return existing

    log = HitlLog(
        message_id=message_id,
        sale_id=sale_id,
        status=HitlStatus.CONFIRMED,
        confirmed_content=confirmed_content,
        confirmed_at=utcnow(),
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log
