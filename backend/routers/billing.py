"""Public plan catalogue, business registration, and the owner's own subscription.

Split from `admin_billing.py` on the authorization boundary: everything here is either
unauthenticated (the pricing page) or scoped to the caller's own workspace, while approving
a request and creating a workspace is staff-only and lives in the Admin router.

`/billing/subscription-requests` is deliberately open and rate-limited, the same treatment
`customer_chat.register_customer` gets: it is a public sign-up form, and requiring a token
to ask to become a customer would be a contradiction.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.audit import log_event
from backend.core.deps import get_current_user, require_role
from backend.core.enums import OrganizationRole, UserRole
from backend.core.mysql_client import get_db
from backend.core.rate_limit import anonymous_rate_limit
from backend.models.billing import Organization, Subscription
from backend.models.user import User
from backend.schemas.billing import (
    PlanResponse,
    QuoteResponse,
    SubscriptionChangeRequest,
    SubscriptionRequestCreate,
    SubscriptionRequestResponse,
    SubscriptionResponse,
    UsageResponse,
)
from backend.services import billing_service

router = APIRouter(prefix="/billing", tags=["Billing"])


def _subscription_response(db: Session, subscription: Subscription) -> SubscriptionResponse:
    """Assemble the owner-facing view, pricing it from the plan rather than from anything
    stored on the subscription — a price change must show up here without a backfill."""
    plan = billing_service.get_plan(db, subscription.plan_id)
    organization = db.get(Organization, subscription.organization_id)
    usage = billing_service.get_or_create_usage(db, subscription.organization_id)
    included = billing_service.included_conversations(plan, subscription.seats)

    return SubscriptionResponse(
        id=subscription.id,
        organization_id=subscription.organization_id,
        organization_name=organization.name if organization else "",
        plan=PlanResponse.model_validate(plan),
        seats=subscription.seats,
        seats_used=billing_service.count_members(db, subscription.organization_id),
        status=subscription.status,  # type: ignore[arg-type]
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        monthly_total_vnd=plan.price_per_seat_vnd * subscription.seats,
        pending_plan_id=subscription.pending_plan_id,  # type: ignore[arg-type]
        pending_seats=subscription.pending_seats,
        cancelled_at=subscription.cancelled_at,
        usage=UsageResponse(
            period=usage.period,
            conversations_used=usage.conversations_used,
            conversations_included=included,
            overage_conversations=usage.overage_conversations,
            overage_charge_vnd=usage.overage_conversations * plan.overage_price_vnd,
        ),
    )


def _owned_subscription(db: Session, user: User, *, require_owner: bool) -> Subscription:
    """The caller's workspace subscription, or a 404/403 explaining why not.

    404 rather than 403 when there is no membership at all: a Sale who was never added to
    a workspace has no subscription to be forbidden from.
    """
    membership = billing_service.get_membership(db, user.id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tài khoản chưa thuộc workspace nào.")
    if require_owner and membership.role != OrganizationRole.OWNER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Chỉ chủ workspace mới thay đổi được gói dịch vụ."
        )

    subscription = billing_service.get_subscription_for_org(db, membership.organization_id)
    if subscription is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workspace chưa có gói dịch vụ.")
    return subscription


@router.get("/plans", response_model=list[PlanResponse])
async def get_plans(db: Session = Depends(get_db)) -> list[PlanResponse]:
    """The published pricing table. Unauthenticated: the marketing page renders from this
    so the site and the biller can never quote different numbers."""
    return [PlanResponse.model_validate(plan) for plan in billing_service.list_active_plans(db)]


@router.get("/quote", response_model=QuoteResponse)
async def get_quote(plan_id: str, seats: int, db: Session = Depends(get_db)) -> QuoteResponse:
    """Price a plan at a seat count for the confirmation screen, so the total the applicant
    approves is computed by the same code that will store it."""
    try:
        return billing_service.quote(db, plan_id, seats)
    except billing_service.BillingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/subscription-requests",
    response_model=SubscriptionRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def submit_subscription_request(
    payload: SubscriptionRequestCreate,
    db: Session = Depends(get_db),
    _: None = Depends(anonymous_rate_limit),
) -> SubscriptionRequestResponse:
    """A business applies for a plan. Creates no account and no workspace — an Admin does
    that on approval, which is the whole payment flow until a gateway exists."""
    try:
        request = billing_service.create_subscription_request(db, payload)
    except billing_service.BillingError as exc:
        log_event("billing.request.rejected", reason=str(exc))
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    log_event(
        "billing.request.submitted",
        request_id=request.id,
        plan_id=request.plan_id,
        seats=request.seats,
        company_name=request.company_name,
    )
    return SubscriptionRequestResponse.model_validate(request)


@router.get("/my-subscription", response_model=SubscriptionResponse)
async def get_my_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> SubscriptionResponse:
    """What the caller's own workspace is paying for. Any member may read it; only the
    owner may change it."""
    return _subscription_response(db, _owned_subscription(db, user, require_owner=False))


@router.post("/subscription/change", response_model=SubscriptionResponse)
async def change_subscription(
    payload: SubscriptionChangeRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> SubscriptionResponse:
    """Upgrade now, or schedule a downgrade for the next renewal."""
    if payload.plan_id is None and payload.seats is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Cần chọn gói mới hoặc số seat mới."
        )

    subscription = _owned_subscription(db, user, require_owner=True)
    try:
        updated = billing_service.change_subscription(db, subscription, plan_id=payload.plan_id, seats=payload.seats)
    except billing_service.BillingError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    log_event(
        "billing.subscription.changed",
        user_id=user.id,
        organization_id=updated.organization_id,
        plan_id=updated.plan_id,
        seats=updated.seats,
        pending_plan_id=updated.pending_plan_id,
        pending_seats=updated.pending_seats,
    )
    return _subscription_response(db, updated)


@router.post("/subscription/cancel", response_model=SubscriptionResponse)
async def cancel_subscription(
    db: Session = Depends(get_db),
    user: User = Depends(require_role(UserRole.SALE, UserRole.ADMIN)),
) -> SubscriptionResponse:
    """Stop renewing. Access continues until the end of the period already paid for."""
    subscription = _owned_subscription(db, user, require_owner=True)
    try:
        cancelled = billing_service.cancel_subscription(db, subscription)
    except billing_service.BillingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    log_event(
        "billing.subscription.cancelled",
        user_id=user.id,
        organization_id=cancelled.organization_id,
        period_end=cancelled.current_period_end.isoformat(),
    )
    return _subscription_response(db, cancelled)


__all__ = ["get_current_user", "router"]
