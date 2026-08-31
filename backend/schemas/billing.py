from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PlanId = Literal["starter", "growth", "enterprise"]
SubscriptionStatusValue = Literal["trialing", "active", "past_due", "cancelled", "expired"]
RequestStatusValue = Literal["pending", "contacted", "approved", "rejected"]
MemberRoleValue = Literal["owner", "admin", "member"]


class PlanResponse(BaseModel):
    """One row of the public pricing table. Served unauthenticated to the marketing page,
    so it carries nothing but the published terms."""

    model_config = ConfigDict(from_attributes=True)

    id: PlanId
    name: str
    description: str | None = None
    price_per_seat_vnd: int
    min_seats: int
    conversations_per_seat: int | None = None
    overage_price_vnd: int
    support_note: str | None = None
    sort_order: int


class SubscriptionRequestCreate(BaseModel):
    """The business registration form behind the pricing page's Đăng ký button.

    `password` is collected here rather than after approval so an approved applicant has a
    working account the moment an Admin says yes, without a second email round trip. It is
    hashed before it touches the database and never returned.
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: PlanId
    seats: int = Field(ge=1, le=1000)

    company_name: str = Field(min_length=2, max_length=255)
    contact_name: str = Field(min_length=2, max_length=255)
    contact_email: EmailStr
    contact_phone: str = Field(min_length=8, max_length=20)
    password: str = Field(min_length=8, max_length=128)

    tax_code: str | None = Field(default=None, max_length=30)
    billing_address: str | None = Field(default=None, max_length=255)
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("company_name", "contact_name", "contact_phone", "tax_code", "billing_address", "note")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class QuoteResponse(BaseModel):
    """What the applicant is told the plan costs, computed by the backend.

    Returned by the review step so the number on the confirmation screen is the same one
    that gets stored on the request — a subtotal the frontend worked out on its own could
    drift from the seeded price without anyone noticing.
    """

    plan_id: PlanId
    plan_name: str
    seats: int
    price_per_seat_vnd: int
    monthly_total_vnd: int
    included_conversations: int | None = None
    overage_price_vnd: int


class SubscriptionRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: PlanId
    seats: int
    company_name: str
    contact_name: str
    contact_email: str
    contact_phone: str
    tax_code: str | None = None
    billing_address: str | None = None
    note: str | None = None
    quoted_price_per_seat_vnd: int
    quoted_monthly_total_vnd: int
    status: RequestStatusValue
    review_note: str | None = None
    reviewed_at: datetime | None = None
    organization_id: int | None = None
    created_at: datetime


class SubscriptionRequestListResponse(BaseModel):
    items: list[SubscriptionRequestResponse]
    total: int
    offset: int
    limit: int


class SubscriptionRequestReview(BaseModel):
    """An Admin moving a request along. `approve` creates the workspace and the owner
    account; the other verdicts only annotate the row."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["contacted", "approved", "rejected"]
    review_note: str | None = Field(default=None, max_length=2000)


class UsageResponse(BaseModel):
    period: str
    conversations_used: int
    conversations_included: int | None = None
    overage_conversations: int
    overage_charge_vnd: int


class SubscriptionResponse(BaseModel):
    """The owner's view of what their workspace is paying for right now."""

    id: int
    organization_id: int
    organization_name: str
    plan: PlanResponse
    seats: int
    seats_used: int
    status: SubscriptionStatusValue
    current_period_start: datetime
    current_period_end: datetime
    monthly_total_vnd: int
    pending_plan_id: PlanId | None = None
    pending_seats: int | None = None
    cancelled_at: datetime | None = None
    usage: UsageResponse


class SubscriptionChangeRequest(BaseModel):
    """Upgrade or downgrade. At least one of the two fields must be set; the service
    decides whether the change lands now or at the next renewal."""

    model_config = ConfigDict(extra="forbid")

    plan_id: PlanId | None = None
    seats: int | None = Field(default=None, ge=1, le=1000)


class OrganizationMemberResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: int
    username: str
    email: str
    full_name: str | None = None
    role: MemberRoleValue
    created_at: datetime
