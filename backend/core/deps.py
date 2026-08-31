from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.core.security import decode_token
from backend.models.user import User
from backend.repositories.user import get_user_by_username

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise credentials_error

    username = payload.get("sub")
    if username is None:
        raise credentials_error

    user = get_user_by_username(db, username)
    if user is None or not user.is_active:
        raise credentials_error

    return user


def get_optional_current_user(
    token: str | None = Depends(oauth2_scheme_optional), db: Session = Depends(get_db)
) -> User | None:
    """Same validation as `get_current_user`, but `None` instead of a 401 when there is no
    (or an invalid/expired) token — for endpoints the customer chat flow must serve to both
    anonymous visitors and logged-in customers alike.
    """
    if token is None:
        return None

    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        return None

    username = payload.get("sub")
    if username is None:
        return None

    user = get_user_by_username(db, username)
    if user is None or not user.is_active:
        return None

    return user


def require_role(*roles: UserRole):
    """Allow users holding any one of the given roles.

    Pass a single role to lock an endpoint down (e.g. require_role(UserRole.ADMIN)),
    or several when both roles share a flow (e.g. Chat is open to SALE + ADMIN).
    """
    allowed = set(roles)

    def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
        return user

    return _dependency
