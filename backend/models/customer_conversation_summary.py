from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class CustomerConversationSummary(Base):
    """Durable, incremental handoff brief for one registered customer.

    The raw AI and live-Sale transcripts remain isolated in their own ``chat_sessions``
    rows.  This table stores only the derived internal brief and a high-water mark, so a
    later refresh sends Gemini the previous compact metadata plus messages added since the
    last successful run instead of paying to replay the customer's entire history.
    """

    __tablename__ = "customer_conversation_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    customer_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id"),
        nullable=False,
        unique=True,
    )
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False)

    last_processed_message_id: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_message_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(32), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)

    generated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
