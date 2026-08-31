from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.enums import LeadTier
from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class Lead(Base):
    """A prospective buyer and how ready they are to buy — one row per PERSON.

    Deliberately not a column on `chat_sessions`: `ChatSession.channel` splits one
    customer's AI conversation and their live-Sale thread into two separate rows, and
    `sale_live` resolves LIVE rows only. A tier written on the AI row would be invisible on
    exactly the row the Sale is looking at, and dual-writing both rows to describe one
    person is the bug, not the fix.

    Identity mirrors `ChatSession`'s own ownership invariant, enforced at the application
    layer for the same reason (no portable CHECK across the MySQL/SQLite versions targeted):
      - Anonymous visitor: `visitor_token` set, `customer_id` NULL.
      - Registered customer: `customer_id` set, `visitor_token` NULL.
    Both columns are UNIQUE and nullable — MySQL and SQLite both permit many NULLs under
    UNIQUE, the same trick `chat_sessions.visitor_token` already relies on — so one person
    has exactly one row in either state. Registration transfers the row rather than creating
    a second (see `repositories.lead.claim_anonymous_lead`), so a visitor's accumulated
    score survives them signing up.

    No contact columns here. Contact details are only ever captured at registration, so they
    always have a `users` row to live on; copying them here would create a drift surface
    with no anonymous case to justify it.
    """

    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    customer_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, unique=True, index=True
    )
    visitor_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"), nullable=True, index=True)

    tier: Mapped[str] = mapped_column(
        String(10), default=LeadTier.COLD, server_default=LeadTier.COLD.value, nullable=False, index=True
    )
    score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    rule_score: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    soft_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    urgency: Mapped[str | None] = mapped_column(String(12), nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(20), nullable=True)

    signals: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    detection_method: Mapped[str] = mapped_column(String(20), default="rule", server_default="rule", nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    analysis_version: Mapped[str | None] = mapped_column(String(20), nullable=True)

    turn_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    llm_scored_turn: Mapped[int | None] = mapped_column(Integer, nullable=True)

    scored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    llm_scored_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
