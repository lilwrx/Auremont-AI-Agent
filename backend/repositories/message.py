from sqlalchemy.orm import Session

from backend.core.enums import MessageEmotion, MessageSender
from backend.models.message import Message


def create_message(
    db: Session,
    session_id: int | None,
    sender: MessageSender,
    content: str,
    citations: list[dict] | None = None,
    images: list[dict] | None = None,
    verifier_score: float | None = None,
    requires_hitl: bool = False,
    faithfulness: float | None = None,
    answer_relevancy: float | None = None,
    completeness: float | None = None,
    failure_mode: str | None = None,
    emotion: MessageEmotion | None = None,
    quick_replies: list[str] | None = None,
    listings: list[dict] | None = None,
    suggested_questions: list[str] | None = None,
) -> Message:
    message = Message(
        session_id=session_id,
        sender=sender,
        content=content,
        citations=citations,
        images=images,
        verifier_score=verifier_score,
        requires_hitl=requires_hitl,
        faithfulness=faithfulness,
        answer_relevancy=answer_relevancy,
        completeness=completeness,
        failure_mode=failure_mode,
        emotion=emotion,
        quick_replies=quick_replies or None,
        listings=listings or None,
        suggested_questions=suggested_questions or None,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def list_messages_for_session(db: Session, session_id: int) -> list[Message]:
    return db.query(Message).filter(Message.session_id == session_id).order_by(Message.created_at).all()


def history_for_pipeline(messages: list[Message]) -> list[dict]:
    """Shape `list_messages_for_session`'s rows into what `agent_pipeline.run_pipeline`'s
    `history` param expects — plain dicts, not ORM objects, so the pipeline module has no
    reason to import `Message`/SQLAlchemy at all. Shared by customer_chat.py and
    sale_chat.py rather than each rolling its own so the shape can't drift between them.
    """
    return [{"sender": m.sender, "content": _content_with_listing_identity(m)} for m in messages]


def _content_with_listing_identity(message: Message) -> str:
    """The turn's text, plus the mã căn of any listing cards it displayed.

    A card carries the unit's identity (mã căn, tower) in structured fields the asker can
    see on screen but which never appear in `content`. Without them here, a follow-up like
    "căn này ở tầng bao nhiêu?" reaches the model with no unit code anywhere in its
    context, and the only honest thing left is to ask the customer to repeat the code it
    had just shown them.

    Only identity is added, not the figures: area and price are already in the answer text,
    while the mã căn is the one field that lets the next turn look the unit up again.
    """
    listings = message.listings or []
    codes = [
        code
        for listing in listings
        if isinstance(listing, dict) and (code := str(listing.get("unit_code") or "").strip())
    ]
    if not codes:
        return message.content

    labelled = [
        f"{code} (tòa {tower})" if (tower := _listing_tower(listings, code)) else code for code in dict.fromkeys(codes)
    ]
    return f"{message.content}\n[Thẻ căn đã hiển thị: {'; '.join(labelled)}]"


def _listing_tower(listings: list, unit_code: str) -> str:
    return next(
        (
            str(listing.get("tower") or "").strip()
            for listing in listings
            if isinstance(listing, dict) and str(listing.get("unit_code") or "").strip() == unit_code
        ),
        "",
    )


def get_message(db: Session, message_id: int) -> Message | None:
    return db.query(Message).filter(Message.id == message_id).first()


def delete_messages_for_session(db: Session, session_id: int) -> None:
    db.query(Message).filter(Message.session_id == session_id).delete(synchronize_session=False)
    db.commit()
