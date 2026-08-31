from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.enums import SessionChannel, SessionStatus
from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class ChatSession(Base):
    """A consultation session — a Sale's session with a customer, OR a public customer-chat
    session (anonymous or a logged-in CUSTOMER account).

    `sale_id` / `customer_id` / `visitor_token` describe ownership, enforced at the
    application layer rather than a DB constraint (not reliably expressible as a portable
    CHECK across the MySQL/SQLite versions this app targets):
      - Sale/Admin session (Sale consulting on their own): `sale_id` set, the other two NULL.
      - Anonymous customer session: `visitor_token` set, the other two NULL.
      - Registered customer session, not yet claimed by a Sale: `customer_id` set (once
        claimed from anonymous, or created directly while logged in), the other two NULL.
      - Registered customer session claimed by a Sale (live handoff, `status=SALE_HANDLING`):
        BOTH `customer_id` and `sale_id` set, `visitor_token` NULL, and `channel=LIVE` — a
        distinct row from that customer's `channel=AI` conversation, which the Sale never sees. Code paths that list a
        Sale's own AI-consult sessions (`list_sessions_for_sale`) or resolve their ownership
        (`sale_chat._owned_session`) must exclude rows with `customer_id` set, or a claimed
        customer session leaks into the Sale's unrelated self-consult session list/access.

    `status` (see `SessionStatus`) only has meaning for a customer session (anonymous or
    CUSTOMER-owned): whether the AI is still answering (BOT_HANDLING), the customer is
    waiting for a Sale to pick it up (WAITING_SALE), or a Sale has taken over and the AI must
    stay silent (SALE_HANDLING). Sale-authored sessions leave it at the default, unused.
    """

    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    sale_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(20), default=SessionStatus.BOT_HANDLING, nullable=False)

    channel: Mapped[str] = mapped_column(String(10), default=SessionChannel.AI, nullable=False, index=True)

    handoff_requested_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    visitor_token: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True, index=True)

    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    customer_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    project_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("projects.id"), nullable=True, index=True)

    ai_questions_today: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    ai_questions_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
