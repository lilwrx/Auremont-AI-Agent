"""Staff-side review of business subscription requests.

Separate from `billing.py` because the authorization is different in kind: these endpoints
act on *other people's* workspaces and are gated on `UserRole.ADMIN` at the router level,
the same way `admin_eval` and `admin_sales` are.

Approving is the one call that creates a workspace, so it is the only place in the product
where an account is created without the person being at a keyboard. The credentials are the
ones the applicant chose on the public form; nothing is generated or emailed here, which is
why the response tells the Admin which login to hand over.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.core.audit import log_event
from backend.core.deps import require_role
from backend.core.enums import SubscriptionRequestStatus, UserRole
from backend.core.mysql_client import get_db
from backend.models.billing import SubscriptionRequest
from backend.models.user import User
from backend.schemas.billing import (
    SubscriptionRequestListResponse,
    SubscriptionRequestResponse,
    SubscriptionRequestReview,
)
from backend.services import billing_service

router = APIRouter(
    prefix="/admin/billing",
    tags=["Admin Billing"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


@router.get("/subscription-requests", response_model=SubscriptionRequestListResponse)
async def list_subscription_requests(
    request_status: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> SubscriptionRequestListResponse:
    """The review queue, newest first. Filterable by status so the pending ones are one
    click away from the default view."""
    filters = []
    if request_status is not None:
        filters.append(SubscriptionRequest.status == request_status)

    total = int(db.scalar(select(func.count(SubscriptionRequest.id)).where(*filters)) or 0)
    rows = list(
        db.scalars(
            select(SubscriptionRequest)
            .where(*filters)
            .order_by(SubscriptionRequest.created_at.desc(), SubscriptionRequest.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return SubscriptionRequestListResponse(
        items=[SubscriptionRequestResponse.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch("/subscription-requests/{request_id}", response_model=SubscriptionRequestResponse)
async def review_subscription_request(
    request_id: int,
    payload: SubscriptionRequestReview,
    db: Session = Depends(get_db),
    reviewer: User = Depends(require_role(UserRole.ADMIN)),
) -> SubscriptionRequestResponse:
    """Move one request along.

    `approved` provisions the workspace, the owner account and the subscription in a single
    transaction; `contacted` and `rejected` only annotate the row, leaving the applicant
    with no account either way.
    """
    request = db.get(SubscriptionRequest, request_id)
    if request is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy yêu cầu.")

    try:
        if payload.status == SubscriptionRequestStatus.APPROVED:
            organization = billing_service.approve_request(db, request, reviewer, payload.review_note)
            log_event(
                "billing.request.approved",
                request_id=request.id,
                organization_id=organization.id,
                reviewer_id=reviewer.id,
                plan_id=request.plan_id,
                seats=request.seats,
            )
        else:
            billing_service.mark_request(db, request, reviewer, payload.status, payload.review_note)
            log_event(
                "billing.request.reviewed",
                request_id=request.id,
                reviewer_id=reviewer.id,
                status=payload.status,
            )
    except billing_service.BillingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    db.refresh(request)
    return SubscriptionRequestResponse.model_validate(request)
