from datetime import datetime

from pydantic import BaseModel

from backend.core.enums import LeadPurpose, LeadTier, LeadUrgency


class LiveInboxEntry(BaseModel):
    """One row in the Sale-facing "Khách đang chờ" queue (routers/sale_live.py)."""

    session_id: int
    customer_label: str
    last_message_preview: str
    waiting_since: datetime | None

    lead_tier: LeadTier = LeadTier.COLD
    lead_score: int = 0
    lead_reason: str | None = None
    customer_name: str | None = None
    customer_phone: str | None = None


class LeadSignalDetail(BaseModel):
    """One fired scoring signal, for the full breakdown panel on the chat screen itself.

    `LiveInboxEntry.lead_reason` (a single joined string) is enough for a queue row; the
    chat screen has room for the actual evidence — this is that evidence, one row per
    signal that fired, so a Sale can check the tier rather than just trust it.
    """

    label: str
    points: int


class LeadDetailResponse(BaseModel):
    """Full lead breakdown for the Sale actually talking to this customer right now.

    `null` when nobody has scored this session yet (e.g. the very first message of a fresh
    live handoff) — the frontend renders an explicit "chưa có dữ liệu" state rather than a
    misleading COLD badge with zero evidence behind it.
    """

    customer_label: str
    customer_name: str | None = None
    customer_phone: str | None = None

    lead_tier: LeadTier
    lead_score: int
    rule_score: int
    soft_score: int | None = None
    urgency: LeadUrgency | None = None
    purpose: LeadPurpose | None = None
    confidence: float | None = None
    detection_method: str

    turn_count: int
    scored_at: datetime | None = None

    signals: list[LeadSignalDetail] = []
    llm_reason: str | None = None

    next_action: str = ""
    budgets: list[str] = []
    unit_types: list[str] = []
    projects: list[str] = []


class SaleLiveMessageRequest(BaseModel):
    content: str


class SaleSuggestResponse(BaseModel):
    """A draft answer for the Sale to review/edit — never persisted as a message until the
    Sale actually sends it via POST /sale/live-inbox/{id}/reply."""

    draft: str
    requires_hitl: bool = False
