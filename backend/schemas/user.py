from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from backend.core.enums import UserRole


class UserBase(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr
    role: UserRole = UserRole.SALE


class UserCreate(UserBase):
    password: str = Field(..., min_length=8)


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    permissions: list[str] | None = None
    is_active: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"  # noqa: S105 - OAuth token scheme, not a credential
    user: UserResponse
