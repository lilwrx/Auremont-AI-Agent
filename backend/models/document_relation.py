from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.enums import DocumentRelationType, DocumentReviewStatus
from backend.core.mysql_client import Base
from backend.models import (  # noqa: F401
    chat_session,
    conflict_flag,
    document,
    document_relation,
    feedback,
    hitl_log,
    message,
    project,
    user,
)
from backend.utils.time import utcnow


class DocumentRelation(Base):
    """How a newly uploaded document affects an existing one.

    Ví dụ:
    - Chính sách tháng 08 thay thế chính sách tháng 07.
    - Bảng giá đợt 2 cập nhật bảng giá đợt 1.
    - Nghị định mới bãi bỏ một nghị định cũ.
    """

    __tablename__ = "document_relations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("documents.id"),
        nullable=False,
        index=True,
    )
    target_document_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("documents.id"),
        nullable=False,
        index=True,
    )

    relation_type: Mapped[str] = mapped_column(
        String(30),
        default=DocumentRelationType.RELATED_TO,
        nullable=False,
        index=True,
    )

    scope_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    review_status: Mapped[str] = mapped_column(
        String(30),
        default=DocumentReviewStatus.PENDING,
        nullable=False,
        index=True,
    )

    reviewed_by: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
