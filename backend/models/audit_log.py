from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class AuditLog(Base):
    """Durable business-event trail: who did what, when.

    stdout logs answer "what went wrong just now" and are gone once the container
    is replaced. This table answers "who logged in last Tuesday" and "which Sale
    confirmed that price" months later, which is what an audit trail is for.

    Diagnostic logs deliberately do **not** land here — only `salesmate.audit`
    events. Tracebacks and access lines are high volume, short-lived, and belong
    in the log collector, not in the operational database.
    """

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    event: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False, index=True)

    username: Mapped[str | None] = mapped_column(String(50), nullable=True)

    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
