from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.deps import require_role
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.models.feedback import Feedback
from backend.models.user import User
from backend.repositories.chat_session import get_session
from backend.repositories.feedback import (
    create_feedback,
    get_question_for_answer,
    list_feedback_for_message,
    list_top_failed,
)
from backend.repositories.message import get_message
from backend.schemas.feedback import FailedQuestion, FeedbackCreate, FeedbackResponse

router = APIRouter(
    prefix="/feedback",
    tags=["Feedback"],
    dependencies=[Depends(require_role(UserRole.SALE, UserRole.ADMIN))],
)


def _owned_message(db: Session, message_id: int, user: User):
    """Fetch a message; 404 unless it belongs to a conversation the caller owns.

    Message ids are sequential, so without this an authenticated user could walk them to
    read or rate answers from every other Sale's consultations. Returns 404 rather than
    403 so the response does not reveal which message ids exist — same contract as
    `routers/hitl.py::confirm_hitl`.
    """
    message = get_message(db, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    session = get_session(db, message.session_id) if message.session_id else None
    if session is None or session.sale_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    return message


@router.post("", response_model=FeedbackResponse, status_code=status.HTTP_201_CREATED)
async def submit_feedback(
    payload: FeedbackCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> FeedbackResponse:
    """The Feedback button under each answer — a Sale reports it as wrong or incomplete."""
    _owned_message(db, payload.message_id, user)

    return create_feedback(
        db,
        message_id=payload.message_id,
        feedback_type=payload.type,
        comment=payload.comment,
        user_id=user.id,
    )


@router.get("/message/{message_id}", response_model=list[FeedbackResponse])
async def get_feedback_for_message(
    message_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> list[Feedback]:
    if user.role != UserRole.ADMIN:
        _owned_message(db, message_id, user)
    return list_feedback_for_message(db, message_id)


@router.get("/top-failed", response_model=list[FailedQuestion])
async def get_top_failed_questions(
    limit: int = 10,
    db: Session = Depends(get_db),
    _: User = Depends(require_role(UserRole.ADMIN)),
) -> list[FailedQuestion]:
    """Top questions the AI answered badly, aggregated from Sale feedback."""
    results: list[FailedQuestion] = []
    for message_id, count in list_top_failed(db, limit=limit):
        question = get_question_for_answer(db, message_id)
        if question is None:
            continue
        results.append(FailedQuestion(message_id=message_id, question=question, feedback_count=count))
    return results
