from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.audit import log_event
from backend.core.deps import require_role
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.models.user import User
from backend.repositories.chat_session import get_session
from backend.repositories.hitl_log import confirm_message
from backend.repositories.message import get_message
from backend.schemas.hitl_log import HitlConfirmRequest, HitlLogResponse

router = APIRouter(prefix="/hitl", tags=["HITL"], dependencies=[Depends(require_role(UserRole.SALE, UserRole.ADMIN))])


@router.post("/{message_id}/confirm", response_model=HitlLogResponse)
async def confirm_hitl(
    message_id: int,
    payload: HitlConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> HitlLogResponse:
    """Mandatory confirmation before a price/commitment answer may be sent to a customer.

    Only the owner of the conversation may confirm. Without that check any authenticated
    Sale could confirm any message by guessing its id, putting another user's name against
    a commitment they never read.
    """
    message = get_message(db, message_id)
    if message is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    session = get_session(db, message.session_id) if message.session_id else None
    if session is None or session.sale_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")

    if not message.requires_hitl:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Message does not require HITL")

    confirmed = confirm_message(
        db,
        message_id=message_id,
        sale_id=user.id,
        confirmed_content=payload.confirmed_content,
    )

    log_event(
        "hitl.confirm",
        message_id=message_id,
        hitl_log_id=confirmed.id,
        user_id=user.id,
        content_len=len(payload.confirmed_content or ""),
        edited=(payload.confirmed_content or "") != (message.content or ""),
    )
    return confirmed
