import time

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.ai.intent import is_customer_memory_query
from backend.core.audit import log_event, redact_and_truncate
from backend.core.config import settings
from backend.core.deps import require_role
from backend.core.enums import MessageEmotion, MessageSender, UserRole
from backend.core.mysql_client import get_db
from backend.models.chat_session import ChatSession
from backend.models.user import User
from backend.repositories.chat_session import (
    create_session,
    delete_session,
    get_session,
    list_sessions_for_sale,
    set_title_if_empty,
)
from backend.repositories.feedback import delete_feedback_for_session
from backend.repositories.hitl_log import confirmed_message_ids, delete_hitl_logs_for_session
from backend.repositories.message import (
    create_message,
    delete_messages_for_session,
    history_for_pipeline,
    list_messages_for_session,
)
from backend.schemas.chat_session import ChatSessionCreate, ChatSessionResponse
from backend.schemas.message import MessageResponse
from backend.services import agent_pipeline, memory_service, reflection_memory, search_criteria

router = APIRouter(
    prefix="/sale/sessions",
    tags=["Sale Chat"],
    dependencies=[Depends(require_role(UserRole.SALE, UserRole.ADMIN))],
)


class SaleAskRequest(BaseModel):
    content: str


def _conversation_history(db: Session, session_id: int) -> list[dict]:
    """The session's short-term working memory, oldest first.

    Edge-case notices are dropped rather than replayed. "Không đủ thông tin, liên hệ Admin"
    and the inventory-down message are UI states, not things the assistant said about the
    project; feeding them back as context invites the model to treat "there is no data" as
    an established fact and repeat it after retrieval has since succeeded.
    """
    messages = [
        message
        for message in list_messages_for_session(db, session_id)
        if message.sender == MessageSender.SALE or message.content not in agent_pipeline.NOTICE_MESSAGES
    ]
    return history_for_pipeline(messages)


def _owned_session(db: Session, session_id: int, user: User):
    """Fetch a chat session; 404 if it does not exist or does not belong to the caller.

    Both SALE and ADMIN can chat, but each only sees their own sessions: a session
    holds per-customer consultation history, so one user must never read or delete
    another's. Returns 404 rather than 403 so the response does not reveal which
    session ids exist.

    `customer_id is not None` rejects a customer session this Sale has claimed via the
    live-inbox flow (routers/sale_live.py) — that row also carries this Sale's `sale_id`,
    but must only be reachable through the live-inbox endpoints. Routing it through here
    would call the AI pipeline (`ask_in_session` below) on a session a Sale is chatting
    through live, injecting an AI-authored message into the middle of that conversation.
    """
    session = get_session(db, session_id)
    if session is None or session.sale_id != user.id or session.customer_id is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return session


@router.post("", response_model=ChatSessionResponse, status_code=status.HTTP_201_CREATED)
async def create_sale_session(
    payload: ChatSessionCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> ChatSessionResponse:
    return create_session(db, sale_id=user.id, schema=payload)


@router.get("", response_model=list[ChatSessionResponse])
async def list_sale_sessions(
    db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> list[ChatSession]:
    return list_sessions_for_sale(db, sale_id=user.id)


@router.get("/{session_id}/messages", response_model=list[MessageResponse])
async def list_session_messages(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> list[MessageResponse]:
    _owned_session(db, session_id, user)
    messages = list_messages_for_session(db, session_id)

    confirmed = confirmed_message_ids(db, [message.id for message in messages if message.requires_hitl])

    responses = []
    for message in messages:
        response = MessageResponse.model_validate(message)
        response.hitl_confirmed = message.id in confirmed
        responses.append(response)
    return responses


@router.post("/{session_id}/messages", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def ask_in_session(
    session_id: int,
    payload: SaleAskRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> MessageResponse:
    """Agent Pipeline for the Sale flow — flags HITL when a price/commitment risk is detected."""
    session = _owned_session(db, session_id, user)
    set_title_if_empty(db, session, payload.content)

    history = _conversation_history(db, session_id)

    create_message(db, session_id, sender=MessageSender.SALE, content=payload.content)

    memory_key = memory_service.sale_session_key(session_id)
    reflection_scope = reflection_memory.sale_session_scope(session_id)
    if is_customer_memory_query(payload.content):
        memory_service.remember_many(
            memory_key,
            [turn["content"] for turn in history if turn.get("sender") == MessageSender.SALE],
            session.project_id,
            db,
        )
    memory_profile_data = memory_service.load_profile(memory_key)
    memory_profile = memory_service.format_profile(memory_profile_data)

    started = time.perf_counter()
    result = agent_pipeline.run_pipeline(
        payload.content,
        project_id=session.project_id,
        db=db,
        history=history,
        memory_profile=memory_profile,
        session_id=session_id,
        reflection_scope=reflection_scope,
        memory_profile_data=memory_profile_data,
    )
    duration_ms = round((time.perf_counter() - started) * 1000, 2)

    log_event(
        "sale.query",
        session_id=session_id,
        user_id=user.id,
        project_id=session.project_id,
        verifier_score=result.verifier_score,
        faithfulness=result.faithfulness,
        answer_relevancy=result.answer_relevancy,
        completeness=result.completeness,
        failure_mode=result.failure_mode,
        requires_hitl=result.requires_hitl,
        used_cache=result.used_cache,
        citation_count=len(result.citations),
        duration_ms=duration_ms,
        query_len=len(payload.content),
        query=redact_and_truncate(payload.content) if settings.log_query_text else None,
    )
    memory_service.remember(memory_key, payload.content, session.project_id, db=db)

    return create_message(
        db,
        session_id,
        sender=MessageSender.AGENT,
        content=result.draft_answer,
        citations=result.citations,
        images=result.images,
        verifier_score=result.verifier_score,
        requires_hitl=result.requires_hitl,
        faithfulness=result.faithfulness,
        answer_relevancy=result.answer_relevancy,
        completeness=result.completeness,
        failure_mode=result.failure_mode,
        emotion=MessageEmotion(result.emotion) if result.emotion else None,
        suggested_questions=result.suggested_questions,
        listings=result.listings,
    )


@router.delete("/{session_id}/messages", status_code=status.HTTP_204_NO_CONTENT)
async def clear_session_messages(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> None:
    """Clear the chat history but keep the session (the "Xóa chat" button in ChatWindow).

    Order matters: both feedback and HITL confirmations reference messages with non-null
    foreign keys, so they have to go first or the delete fails outright.
    """
    _owned_session(db, session_id, user)
    delete_hitl_logs_for_session(db, session_id)
    delete_feedback_for_session(db, session_id)
    delete_messages_for_session(db, session_id)
    _forget_session_memory(session_id)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_sale_session(
    session_id: int, db: Session = Depends(get_db), user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN))
) -> None:
    """Delete the consultation session and all its messages — the delete button in SessionList."""
    _owned_session(db, session_id, user)
    delete_hitl_logs_for_session(db, session_id)
    delete_feedback_for_session(db, session_id)
    delete_messages_for_session(db, session_id)
    _forget_session_memory(session_id)
    delete_session(db, session_id)


def _forget_session_memory(session_id: int) -> None:
    """Forget every non-MySQL memory layer belonging to one represented customer."""
    memory_service.forget(memory_service.sale_session_key(session_id))
    reflection_memory.forget_all(reflection_memory.sale_session_scope(session_id))
    search_criteria.clear(session_id)
