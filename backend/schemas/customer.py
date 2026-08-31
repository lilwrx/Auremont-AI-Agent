from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from backend.core.enums import SessionStatus
from backend.schemas.message import MessageResponse
from backend.utils.phone import normalise_vn_mobile


class CustomerRegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = None
    session_id: int | None = None
    visitor_token: str | None = None

    @field_validator("phone", mode="before")
    @classmethod
    def _normalise_phone(cls, value: object) -> object:
        return normalise_vn_mobile(value) if isinstance(value, str) else value

    @field_validator("full_name", mode="before")
    @classmethod
    def _strip_full_name(cls, value: object) -> object:
        return value.strip() or None if isinstance(value, str) else value


class AnonymousSessionResponse(BaseModel):
    session_id: int
    visitor_token: str


class AnonymousSessionClaimRequest(BaseModel):
    session_id: int
    visitor_token: str


class CustomerChatSessionCreate(BaseModel):
    title: str | None = None
    project_id: str | None = None


class CustomerChatSessionResponse(BaseModel):
    id: int
    customer_id: int | None = None
    title: str | None = None
    project_id: str | None = None
    status: SessionStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class CustomerAskRequest(BaseModel):
    content: str


class CustomerAskResponse(MessageResponse):
    gate: Literal["turn_limit", "daily_limit", "closing_intent", "human_request"] | None = None
    status: SessionStatus = SessionStatus.BOT_HANDLING
