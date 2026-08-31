"""Development-only helper endpoint used by the E2E suite to create accounts.

This router can create admin accounts, so it must never be reachable in
production. `backend.main` mounts it only when `app_env == "development"`:
gating at mount time (rather than checking inside the handler) means the route
does not exist at all in production, even if someone guesses the path.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from backend.core.mysql_client import get_db
from backend.repositories.user import create_user, get_user_by_username

router = APIRouter(prefix="/__test__", include_in_schema=False)


class SeedUserRequest(BaseModel):
    username: str
    email: EmailStr
    password: str
    role: str = "sale"


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def seed_test_user(payload: SeedUserRequest, db: Session = Depends(get_db)) -> dict:
    if payload.role not in ("sale", "admin"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="role must be 'sale' or 'admin'")

    existing = get_user_by_username(db, payload.username)
    if existing is not None:
        return {"id": existing.id, "username": existing.username, "role": existing.role, "created": False}

    user = create_user(
        db,
        username=payload.username,
        email=payload.email,
        password=payload.password,
        role=payload.role,
    )
    return {"id": user.id, "username": user.username, "role": user.role, "created": True}
