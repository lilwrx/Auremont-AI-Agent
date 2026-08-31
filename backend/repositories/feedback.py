from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.core.enums import FeedbackType, MessageSender
from backend.models.feedback import Feedback
from backend.models.message import Message


def create_feedback(
    db: Session,
    message_id: int,
    feedback_type: FeedbackType,
    comment: str | None = None,
    user_id: int | None = None,
) -> Feedback:
    feedback = Feedback(
        message_id=message_id,
        user_id=user_id,
        type=feedback_type,
        comment=comment,
    )
    db.add(feedback)
    db.commit()
    db.refresh(feedback)
    return feedback


def list_feedback_for_message(db: Session, message_id: int) -> list[Feedback]:
    return db.query(Feedback).filter(Feedback.message_id == message_id).order_by(Feedback.created_at).all()


def delete_feedback_for_session(db: Session, session_id: int) -> None:
    """Drop feedback attached to a session's messages, so those messages can be deleted.

    `feedback.message_id` is a FK onto `messages` with no ON DELETE rule, so deleting a
    message that a Sale had rated raises IntegrityError 1451 and the whole "delete
    session" request fails with a 500. The child rows have to go first.

    Does not commit: the caller deletes messages and the session in the same transaction,
    so either all three go or none do.
    """
    message_ids = db.query(Message.id).filter(Message.session_id == session_id).subquery()
    db.query(Feedback).filter(Feedback.message_id.in_(db.query(message_ids.c.id))).delete(synchronize_session=False)


def list_top_failed(db: Session, limit: int = 10) -> list[tuple[int, int]]:
    """(message_id, feedback_count) for answers reported wrong/incomplete, worst first.

    Counts only WRONG/INCOMPLETE — HELPFUL is not a failure.
    """
    rows = (
        db.query(Feedback.message_id, func.count(Feedback.id).label("total"))
        .filter(Feedback.type.in_([FeedbackType.WRONG, FeedbackType.INCOMPLETE]))
        .group_by(Feedback.message_id)
        .order_by(func.count(Feedback.id).desc())
        .limit(limit)
        .all()
    )
    return [(row.message_id, row.total) for row in rows]


def get_average_verifier_scores(db: Session) -> tuple[float | None, float | None]:
    """(faithfulness_avg, answer_relevancy_avg) across every scored Agent answer.

    Rows where the Verifier never ran are NULL and `func.avg` skips them, so cache hits
    and edge-case notices ("Chưa có dữ liệu dự án", "Tạm thời không tra được tồn kho")
    do not drag the average down — they are not failures of answer quality.

    Returns `(None, None)` when nothing has been scored yet, which the dashboard renders
    as "—" rather than as a misleading 0%.
    """
    row = db.query(
        func.avg(Message.faithfulness),
        func.avg(Message.answer_relevancy),
    ).first()

    if row is None:
        return None, None

    faithfulness, relevancy = row
    return (
        float(faithfulness) if faithfulness is not None else None,
        float(relevancy) if relevancy is not None else None,
    )


def get_question_for_answer(db: Session, answer_message_id: int) -> str | None:
    """The question that produced a reported answer — the Sale message immediately before it.

    Admins need to see the *question*, not the answer, to know which documents to add.
    """
    answer = db.query(Message).filter(Message.id == answer_message_id).first()
    if answer is None:
        return None

    question = (
        db.query(Message)
        .filter(
            Message.session_id == answer.session_id,
            Message.created_at <= answer.created_at,
            Message.id != answer.id,
            Message.sender == MessageSender.SALE,
        )
        .order_by(Message.created_at.desc(), Message.id.desc())
        .first()
    )
    return question.content if question is not None else answer.content
