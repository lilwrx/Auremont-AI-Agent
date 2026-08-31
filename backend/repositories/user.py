from sqlalchemy.orm import Session

from backend.core.enums import UserRole
from backend.core.security import hash_password
from backend.models.user import User


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.query(User).filter(User.email == email).first()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.query(User).filter(User.id == user_id).first()


def list_users_by_ids(db: Session, user_ids: list[int]) -> dict[int, User]:
    """Batched lookup for list endpoints that would otherwise query once per row."""
    if not user_ids:
        return {}
    return {user.id: user for user in db.query(User).filter(User.id.in_(user_ids)).all()}


def create_user(
    db: Session,
    username: str,
    email: str,
    password: str,
    role: str = UserRole.SALE,
    is_active: bool = True,
    full_name: str | None = None,
    phone: str | None = None,
) -> User:
    user = User(
        username=username,
        email=email,
        hashed_password=hash_password(password),
        role=role,
        is_active=is_active,
        full_name=full_name,
        phone=phone,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def ensure_seed_user(db: Session, username: str, email: str, password: str, role: str) -> User:
    """Create the seed account if missing, or reset an existing one to the standard state.

    Idempotent so every backend startup yields the same result: anyone who clones
    the repo can log in with the same accounts, even if someone previously changed
    the password or deactivated that account on a shared database.
    """
    user = get_user_by_username(db, username)
    if user is None:
        return create_user(db, username=username, email=email, password=password, role=role)

    user.email = email
    user.hashed_password = hash_password(password)
    user.role = role
    user.is_active = True
    db.commit()
    db.refresh(user)
    return user
