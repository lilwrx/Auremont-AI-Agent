from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.enums import HitlStatus
from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class HitlLog(Base):
    """Audit trail for the mandatory HITL confirmation on price/commitment answers."""

    __tablename__ = "hitl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    message_id: Mapped[int] = mapped_column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    sale_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(20), default=HitlStatus.PENDING, nullable=False)
    confirmed_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
