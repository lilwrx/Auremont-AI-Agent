"""Workspace billing: who is subscribed, to what, and how much of it they have used.

One file rather than five, because these tables are meaningless apart — a `Subscription`
row is not readable without its `Plan` and `Organization`, and every query in
`services/billing_service.py` touches at least two of them.

The shape is deliberately per-*workspace*, not per-user. A brokerage buys seats for a team
of Sales who share one quota and one invoice; hanging `plan_id` off `users` would make
"how many seats has this company used" a scan of the whole table and give every Sale their
own bill. `organization_members` is the join that keeps one account attached to one
workspace without duplicating the account itself.

Money is stored as whole VND in `Integer` columns, never `Float`: 390000 is exact, and
the smallest unit anyone is billed in is one đồng. Rounding a subtotal through binary
floating point is how an invoice ends up one đồng off the price the customer was shown.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.enums import OrganizationRole, PlanTier, SubscriptionRequestStatus, SubscriptionStatus
from backend.core.mysql_client import Base
from backend.utils.time import utcnow


class Plan(Base):
    """A published plan and its current price — the backend's copy of the pricing page.

    Seeded rather than hard-coded in the frontend so the two can never disagree: the
    marketing page reads `/billing/plans`, and a price change is a row update plus a
    redeploy of nothing. `is_active` retires a plan without deleting it, because
    subscriptions already sold on it still point here and must keep resolving.
    """

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)

    name: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)

    price_per_seat_vnd: Mapped[int] = mapped_column(Integer, nullable=False)
    min_seats: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    conversations_per_seat: Mapped[int | None] = mapped_column(Integer, nullable=True)
    overage_price_vnd: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    support_note: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class Organization(Base):
    """One paying business, and the workspace its Sales share.

    `owner_user_id` is the account that registered and is the only one allowed to change
    or cancel the plan; it is nullable only for the window between an Admin creating the
    workspace and the owner account existing, which `billing_service.activate_request`
    closes in the same transaction.
    """

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True, nullable=False)

    owner_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)

    contact_email: Mapped[str] = mapped_column(String(100), nullable=False)
    contact_phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    tax_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class OrganizationMember(Base):
    """One account's membership of one workspace.

    UNIQUE on `user_id` alone, not on the pair: an account belongs to at most one
    workspace in this product, and enforcing that here is what stops a Sale's quota usage
    from being billed to two companies at once. Seat accounting counts rows here, so a
    member who leaves is deleted rather than flagged — a soft-deleted row that still
    consumed a seat is the bug this avoids.
    """

    __tablename__ = "organization_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, unique=True, index=True)

    role: Mapped[str] = mapped_column(
        String(20), default=OrganizationRole.MEMBER, server_default=OrganizationRole.MEMBER.value, nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)


class Subscription(Base):
    """What one workspace is currently paying for.

    UNIQUE on `organization_id`: a workspace has exactly one subscription, and a plan
    change rewrites this row rather than adding a second — two live rows would make
    "which quota applies right now" ambiguous at exactly the moment it is being enforced.

    `pending_plan_id` and `pending_seats` hold a *downgrade* that has been agreed but must
    not take effect until the paid period ends. Upgrades are applied immediately and never
    land here (see `billing_service.change_subscription`), because a customer who pays more
    should get the larger quota the moment they ask for it.
    """

    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    organization_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=False, unique=True, index=True
    )
    plan_id: Mapped[str] = mapped_column(String(20), ForeignKey("plans.id"), nullable=False, index=True)

    seats: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(20),
        default=SubscriptionStatus.ACTIVE,
        server_default=SubscriptionStatus.ACTIVE.value,
        nullable=False,
        index=True,
    )

    current_period_start: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    current_period_end: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)

    pending_plan_id: Mapped[str | None] = mapped_column(String(20), ForeignKey("plans.id"), nullable=True)
    pending_seats: Mapped[int | None] = mapped_column(Integer, nullable=True)

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class UsageMonthly(Base):
    """AI conversations one workspace spent in one billing month.

    Aggregated here rather than counted from `chat_sessions` on every request: the quota
    check runs on the Sale's request path, and a COUNT over a growing conversation table
    is the wrong thing to put there. `period` is the first day of the month as `YYYY-MM`,
    so the UNIQUE pair is the natural upsert key.
    """

    __tablename__ = "usage_monthly"
    __table_args__ = (UniqueConstraint("organization_id", "period", name="uq_usage_org_period"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    organization_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(7), nullable=False, index=True)

    conversations_used: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    overage_conversations: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class SubscriptionRequest(Base):
    """A business asking to subscribe, before any workspace or account exists.

    This is the whole payment flow in the MVP: the form on the pricing page writes a row
    here, an Admin reads it and either approves it — which creates the organization, the
    owner account and the subscription in one go — or rejects it with a reason.

    The applicant's password is hashed at submission and parked in `hashed_password`, so
    approval can create a working account without a second round trip to a person who may
    have closed the tab days ago. It is cleared once the account exists.
    """

    __tablename__ = "subscription_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True, autoincrement=True)

    plan_id: Mapped[str] = mapped_column(String(20), ForeignKey("plans.id"), nullable=False, index=True)
    seats: Mapped[int] = mapped_column(Integer, nullable=False)

    company_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False)
    contact_email: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    contact_phone: Mapped[str] = mapped_column(String(20), nullable=False)
    tax_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    billing_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    quoted_price_per_seat_vnd: Mapped[int] = mapped_column(Integer, nullable=False)
    quoted_monthly_total_vnd: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(
        String(20),
        default=SubscriptionRequestStatus.PENDING,
        server_default=SubscriptionRequestStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    organization_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("organizations.id"), nullable=True, index=True
    )

    extra: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


__all__ = [
    "Organization",
    "OrganizationMember",
    "Plan",
    "PlanTier",
    "Subscription",
    "SubscriptionRequest",
    "UsageMonthly",
]
