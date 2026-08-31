from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.enums import UserRole
from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class User(Base):
    """An account: a Sale, an Admin, or a registered customer (`UserRole.CUSTOMER`).

    Customer accounts are created by the public chat's registration gate
    (`routers.customer_chat.register_customer`), which is why the contact columns below
    exist and why they are nullable.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True, autoincrement=True)

    username: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)

    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[str] = mapped_column(String(20), default=UserRole.SALE, nullable=False)

    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    permissions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
