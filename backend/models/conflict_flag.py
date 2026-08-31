from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.enums import ConflictStatus
from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class ConflictFlag(Base):
    """Flags contradictory content between two documents, e.g. two price-list versions"""

    __tablename__ = "conflict_flags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    document_id_a: Mapped[int] = mapped_column(Integer, ForeignKey("documents.id"), nullable=False, index=True)
    document_id_b: Mapped[int] = mapped_column(Integer, ForeignKey("documents.id"), nullable=False, index=True)

    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    detection_method: Mapped[str] = mapped_column(
        String(20),
        default="rule",
        server_default="rule",
        nullable=False,
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    similarity_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    conflict_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    analysis_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=ConflictStatus.OPEN, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)

    resolved_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
