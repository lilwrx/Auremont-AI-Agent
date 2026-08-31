from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.core.audit import log_event
from backend.core.deps import get_current_user
from backend.core.mysql_client import get_db
from backend.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from backend.models.user import User
from backend.repositories.user import get_user_by_username
from backend.schemas.user import TokenResponse, UserResponse

router = APIRouter(prefix="/auth", tags=["Auth"])


class RefreshRequest(BaseModel):
    refresh_token: str


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> TokenResponse:
    """Internal Sale/Admin login — the role inside the token drives frontend routing."""
    user = get_user_by_username(db, form.username)

    if not user or not verify_password(form.password, user.hashed_password):
        log_event("auth.login.failure", username=form.username, reason="bad_credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        log_event("auth.login.failure", username=form.username, reason="inactive_user")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Inactive user")

    log_event("auth.login.success", username=user.username, user_id=user.id, role=user.role)
    return TokenResponse(
        access_token=create_access_token(subject=user.username, role=user.role),
        refresh_token=create_refresh_token(subject=user.username),
        user=UserResponse.model_validate(user),
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: Session = Depends(get_db)) -> TokenResponse:
    """Exchange a refresh token for a new access token.

    Access tokens live only a few dozen minutes; without this endpoint a Sale in the
    middle of a consultation would be kicked back to the login screen on expiry.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid refresh token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    claims = decode_token(payload.refresh_token)
    if claims is None:
        log_event("auth.refresh.failure", reason="invalid_token")
        raise credentials_error
    if claims.get("type") != "refresh":
        log_event("auth.refresh.failure", reason="wrong_type")
        raise credentials_error

    username = claims.get("sub")
    if username is None:
        log_event("auth.refresh.failure", reason="no_subject")
        raise credentials_error

    user = get_user_by_username(db, username)
    if user is None or not user.is_active:
        log_event("auth.refresh.failure", reason="unknown_or_inactive_user", username=username)
        raise credentials_error

    return TokenResponse(
        access_token=create_access_token(subject=user.username, role=user.role),
        refresh_token=create_refresh_token(subject=user.username),
        user=UserResponse.model_validate(user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(user: User = Depends(get_current_user)) -> None:
    """Log out.

    JWTs are stateless, so the token stays valid until it expires — the client must
    discard it locally. This endpoint exists to give clients a single call to make
    and to leave an audit trail.
    TODO: add a token denylist (Redis) if immediate revocation becomes necessary.
    """
    log_event("auth.logout", username=user.username, user_id=user.id)
