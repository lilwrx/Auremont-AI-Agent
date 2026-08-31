"""Plan pricing, subscription requests and the workspace they turn into.

The MVP has no payment gateway on purpose: a business submits a request, an Admin reads it
and approves it, and approval is the single call that creates the organization, the owner
account, the membership and the subscription together. Keeping that in one transaction is
what stops a half-created workspace — an organization with no owner, or an owner with no
subscription — from existing at all.

Every price is computed here from the `plans` row, never from anything the client sent.
A seat count and a plan id are the only things the caller gets to choose; multiplying them
is the backend's job, so a tampered request body cannot buy Enterprise at Starter's price.
"""

import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.enums import (
    OrganizationRole,
    SubscriptionRequestStatus,
    SubscriptionStatus,
    UserRole,
)
from backend.core.security import hash_password
from backend.models.billing import (
    Organization,
    OrganizationMember,
    Plan,
    Subscription,
    SubscriptionRequest,
    UsageMonthly,
)
from backend.models.user import User
from backend.repositories.user import get_user_by_email
from backend.schemas.billing import QuoteResponse, SubscriptionRequestCreate
from backend.utils.time import utcnow

logger = logging.getLogger(__name__)

BILLING_PERIOD_DAYS = 30


class BillingError(Exception):
    """A business rule said no. Routers translate this into a 4xx with the message."""


def list_active_plans(db: Session) -> list[Plan]:
    return list(db.scalars(select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)))


def get_plan(db: Session, plan_id: str) -> Plan:
    plan = db.get(Plan, plan_id)
    if plan is None or not plan.is_active:
        raise BillingError(f"Gói '{plan_id}' không tồn tại hoặc đã ngừng bán.")
    return plan


def quote(db: Session, plan_id: str, seats: int) -> QuoteResponse:
    """Price one plan at one seat count, rejecting a seat count the plan does not allow.

    The minimum is part of the published terms, not a UI nicety: Enterprise's per-seat
    price is a volume discount, and honouring it for three seats would sell the cheapest
    rate to the smallest customer.
    """
    plan = get_plan(db, plan_id)
    if seats < plan.min_seats:
        raise BillingError(f"Gói {plan.name} yêu cầu tối thiểu {plan.min_seats} seat.")

    included = plan.conversations_per_seat * seats if plan.conversations_per_seat is not None else None
    return QuoteResponse(
        plan_id=plan.id,  # type: ignore[arg-type]
        plan_name=plan.name,
        seats=seats,
        price_per_seat_vnd=plan.price_per_seat_vnd,
        monthly_total_vnd=plan.price_per_seat_vnd * seats,
        included_conversations=included,
        overage_price_vnd=plan.overage_price_vnd,
    )


def _slugify(name: str, db: Session) -> str:
    """A URL-safe, unique workspace slug derived from the company name.

    Vietnamese names routinely differ only by diacritics once stripped, so a numeric
    suffix is appended until the slug is free rather than assuming the first try is.
    """
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "workspace"
    slug = base
    suffix = 2
    while db.scalar(select(Organization.id).where(Organization.slug == slug)) is not None:
        slug = f"{base}-{suffix}"[:80]
        suffix += 1
    return slug


def create_subscription_request(db: Session, payload: SubscriptionRequestCreate) -> SubscriptionRequest:
    """Record a business's application. Does not create an account or a workspace yet.

    A duplicate email is rejected here rather than at approval time, so the applicant
    finds out while the form is still in front of them.
    """
    if get_user_by_email(db, payload.contact_email) is not None:
        raise BillingError("Email này đã có tài khoản. Vui lòng đăng nhập hoặc dùng email khác.")

    pending = db.scalar(
        select(SubscriptionRequest.id).where(
            SubscriptionRequest.contact_email == payload.contact_email,
            SubscriptionRequest.status.in_([SubscriptionRequestStatus.PENDING, SubscriptionRequestStatus.CONTACTED]),
        )
    )
    if pending is not None:
        raise BillingError("Email này đã có yêu cầu đang chờ duyệt. Bộ phận kinh doanh sẽ liên hệ sớm.")

    priced = quote(db, payload.plan_id, payload.seats)

    request = SubscriptionRequest(
        plan_id=payload.plan_id,
        seats=payload.seats,
        company_name=payload.company_name,
        contact_name=payload.contact_name,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        tax_code=payload.tax_code,
        billing_address=payload.billing_address,
        note=payload.note,
        hashed_password=hash_password(payload.password),
        quoted_price_per_seat_vnd=priced.price_per_seat_vnd,
        quoted_monthly_total_vnd=priced.monthly_total_vnd,
        status=SubscriptionRequestStatus.PENDING,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return request


def approve_request(db: Session, request: SubscriptionRequest, reviewer: User, note: str | None) -> Organization:
    """Turn an approved request into a live workspace, in one transaction.

    Creates the organization, the owner's SALE account, their membership and the
    subscription together — a partially created workspace is worse than a failed approval,
    because nothing in the product knows how to finish one.

    The owner is a SALE, not an ADMIN: `UserRole.ADMIN` is staff of this platform, while
    the buyer is a customer whose authority is scoped to their own workspace by
    `OrganizationRole.OWNER`.
    """
    if request.status == SubscriptionRequestStatus.APPROVED:
        raise BillingError("Yêu cầu này đã được duyệt.")
    if request.hashed_password is None:
        raise BillingError("Yêu cầu này thiếu thông tin mật khẩu; đề nghị khách đăng ký lại.")
    if get_user_by_email(db, request.contact_email) is not None:
        raise BillingError("Email của yêu cầu này đã có tài khoản; không thể tạo workspace trùng.")

    plan = get_plan(db, request.plan_id)

    organization = Organization(
        name=request.company_name,
        slug=_slugify(request.company_name, db),
        contact_email=request.contact_email,
        contact_phone=request.contact_phone,
        tax_code=request.tax_code,
        billing_address=request.billing_address,
    )
    db.add(organization)
    db.flush()

    owner = User(
        username=request.contact_email,
        email=request.contact_email,
        hashed_password=request.hashed_password,
        role=UserRole.SALE,
        full_name=request.contact_name,
        phone=request.contact_phone,
    )
    db.add(owner)
    db.flush()

    organization.owner_user_id = owner.id
    db.add(OrganizationMember(organization_id=organization.id, user_id=owner.id, role=OrganizationRole.OWNER))

    started = utcnow()
    db.add(
        Subscription(
            organization_id=organization.id,
            plan_id=plan.id,
            seats=request.seats,
            status=SubscriptionStatus.ACTIVE,
            current_period_start=started,
            current_period_end=started + timedelta(days=BILLING_PERIOD_DAYS),
        )
    )

    request.status = SubscriptionRequestStatus.APPROVED
    request.review_note = note
    request.reviewed_by_user_id = reviewer.id
    request.reviewed_at = started
    request.organization_id = organization.id
    request.hashed_password = None

    db.commit()
    db.refresh(organization)
    return organization


def mark_request(
    db: Session, request: SubscriptionRequest, reviewer: User, status: str, note: str | None
) -> SubscriptionRequest:
    """Record a non-approving verdict (contacted / rejected) without touching accounts."""
    request.status = status
    request.review_note = note
    request.reviewed_by_user_id = reviewer.id
    request.reviewed_at = utcnow()
    db.commit()
    db.refresh(request)
    return request


def get_membership(db: Session, user_id: int) -> OrganizationMember | None:
    return db.scalar(select(OrganizationMember).where(OrganizationMember.user_id == user_id))


def get_subscription_for_org(db: Session, organization_id: int) -> Subscription | None:
    return db.scalar(select(Subscription).where(Subscription.organization_id == organization_id))


def count_members(db: Session, organization_id: int) -> int:
    return int(
        db.scalar(
            select(func.count(OrganizationMember.id)).where(OrganizationMember.organization_id == organization_id)
        )
        or 0
    )


def current_period(now: datetime | None = None) -> str:
    return (now or utcnow()).strftime("%Y-%m")


def get_or_create_usage(db: Session, organization_id: int, period: str | None = None) -> UsageMonthly:
    key = period or current_period()
    usage = db.scalar(
        select(UsageMonthly).where(UsageMonthly.organization_id == organization_id, UsageMonthly.period == key)
    )
    if usage is None:
        usage = UsageMonthly(organization_id=organization_id, period=key)
        db.add(usage)
        db.commit()
        db.refresh(usage)
    return usage


def included_conversations(plan: Plan, seats: int) -> int | None:
    """The team's pooled monthly allowance, or None when the plan has no hard cap."""
    if plan.conversations_per_seat is None:
        return None
    return plan.conversations_per_seat * seats


def change_subscription(
    db: Session, subscription: Subscription, *, plan_id: str | None, seats: int | None
) -> Subscription:
    """Apply an upgrade now; defer a downgrade to the next renewal.

    Charging more takes effect immediately because the customer asked for more capacity
    and is paying for it. Charging less waits for the period they already paid for to end
    — refunding a partial month is a finance decision this code should not make on its own.

    A seat count below the number of people already in the workspace is refused outright,
    in either direction: silently evicting a Sale mid-conversation is not a billing action.
    """
    target_plan = get_plan(db, plan_id) if plan_id is not None else get_plan(db, subscription.plan_id)
    target_seats = seats if seats is not None else subscription.seats

    members = count_members(db, subscription.organization_id)
    if target_seats < members:
        raise BillingError(
            f"Workspace đang có {members} thành viên; không thể giảm xuống {target_seats} seat. "
            "Vui lòng gỡ bớt thành viên trước."
        )

    if target_seats < target_plan.min_seats:
        raise BillingError(f"Gói {target_plan.name} yêu cầu tối thiểu {target_plan.min_seats} seat.")

    current_total = get_plan(db, subscription.plan_id).price_per_seat_vnd * subscription.seats
    target_total = target_plan.price_per_seat_vnd * target_seats

    if target_total >= current_total:
        subscription.plan_id = target_plan.id
        subscription.seats = target_seats
        subscription.pending_plan_id = None
        subscription.pending_seats = None
        if subscription.status == SubscriptionStatus.CANCELLED:
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.cancelled_at = None
    else:
        subscription.pending_plan_id = target_plan.id
        subscription.pending_seats = target_seats

    db.commit()
    db.refresh(subscription)
    return subscription


def cancel_subscription(db: Session, subscription: Subscription) -> Subscription:
    """Stop the renewal but keep access to the end of the paid period."""
    if subscription.status in (SubscriptionStatus.CANCELLED, SubscriptionStatus.EXPIRED):
        raise BillingError("Gói này đã được hủy.")
    subscription.status = SubscriptionStatus.CANCELLED
    subscription.cancelled_at = utcnow()
    subscription.pending_plan_id = None
    subscription.pending_seats = None
    db.commit()
    db.refresh(subscription)
    return subscription


def has_access(subscription: Subscription | None, now: datetime | None = None) -> bool:
    """Whether this workspace may use the product right now.

    CANCELLED still grants access until `current_period_end`, which is the whole point of
    keeping it distinct from EXPIRED.
    """
    if subscription is None:
        return False
    moment = now or utcnow()
    if subscription.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING):
        return subscription.current_period_end > moment
    if subscription.status == SubscriptionStatus.CANCELLED:
        return subscription.current_period_end > moment
    return False
