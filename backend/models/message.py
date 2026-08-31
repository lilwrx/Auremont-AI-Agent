from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class Message(Base):
    """One turn in a Sale's consultation session — either a Sale question or an Agent answer."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    session_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("chat_sessions.id"), nullable=True, index=True)

    sender: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    citations: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)

    images: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)

    emotion: Mapped[str | None] = mapped_column(String(20), nullable=True)

    quick_replies: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    listings: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    suggested_questions: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    verifier_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    completeness: Mapped[float | None] = mapped_column(Float, nullable=True)
    failure_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    requires_hitl: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
