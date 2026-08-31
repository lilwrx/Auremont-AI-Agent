"""add B2B billing: plans, organizations, subscriptions, usage and requests

Seeds the three published plans in the same revision that creates the table, so a fresh
database serves `/billing/plans` without a separate seeding step. Prices are whole VND
and match the pricing page at the time of writing; a later price change is a row update,
not a migration.

Revision ID: a1b2c3d4e5f6
Revises: f5a6b7c8d9e0
Create Date: 2026-08-30
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = "f5a6b7c8d9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PLANS = [
    {
        "id": "starter",
        "name": "Starter",
        "description": "Cho đội Sale nhỏ mới bắt đầu dùng AI tư vấn.",
        "price_per_seat_vnd": 390_000,
        "min_seats": 1,
        "conversations_per_seat": 150,
        "overage_price_vnd": 2_000,
        "support_note": "Hỗ trợ qua email, phản hồi trong 24h",
        "sort_order": 1,
    },
    {
        "id": "growth",
        "name": "Growth",
        "description": "Cho sàn giao dịch đang mở rộng đội ngũ.",
        "price_per_seat_vnd": 550_000,
        "min_seats": 3,
        "conversations_per_seat": 400,
        "overage_price_vnd": 2_000,
        "support_note": "Hỗ trợ ưu tiên trong giờ hành chính",
        "sort_order": 2,
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "description": "Giá theo quy mô lớn, kèm SLA và tuỳ biến riêng.",
        "price_per_seat_vnd": 420_000,
        "min_seats": 20,
        "conversations_per_seat": None,
        "overage_price_vnd": 2_000,
        "support_note": "SLA riêng, hỗ trợ kỹ thuật 24/7",
        "sort_order": 3,
    },
]


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.String(length=20), primary_key=True),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("price_per_seat_vnd", sa.Integer(), nullable=False),
        sa.Column("min_seats", sa.Integer(), server_default="1", nullable=False),
        sa.Column("conversations_per_seat", sa.Integer(), nullable=True),
        sa.Column("overage_price_vnd", sa.Integer(), server_default="0", nullable=False),
        sa.Column("support_note", sa.String(length=255), nullable=True),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("contact_email", sa.String(length=100), nullable=False),
        sa.Column("contact_phone", sa.String(length=20), nullable=True),
        sa.Column("tax_code", sa.String(length=30), nullable=True),
        sa.Column("billing_address", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_organizations_id", "organizations", ["id"])
    op.create_index("ix_organizations_slug", "organizations", ["slug"], unique=True)
    op.create_index("ix_organizations_owner_user_id", "organizations", ["owner_user_id"])

    op.create_table(
        "organization_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("role", sa.String(length=20), server_default="member", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_organization_members_id", "organization_members", ["id"])
    op.create_index("ix_organization_members_organization_id", "organization_members", ["organization_id"])
    op.create_index("ix_organization_members_user_id", "organization_members", ["user_id"], unique=True)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("plan_id", sa.String(length=20), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("current_period_start", sa.DateTime(), nullable=False),
        sa.Column("current_period_end", sa.DateTime(), nullable=False),
        sa.Column("pending_plan_id", sa.String(length=20), sa.ForeignKey("plans.id"), nullable=True),
        sa.Column("pending_seats", sa.Integer(), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_subscriptions_id", "subscriptions", ["id"])
    op.create_index("ix_subscriptions_organization_id", "subscriptions", ["organization_id"], unique=True)
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])
    op.create_index("ix_subscriptions_status", "subscriptions", ["status"])
    op.create_index("ix_subscriptions_current_period_end", "subscriptions", ["current_period_end"])

    op.create_table(
        "usage_monthly",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("conversations_used", sa.Integer(), server_default="0", nullable=False),
        sa.Column("overage_conversations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "period", name="uq_usage_org_period"),
    )
    op.create_index("ix_usage_monthly_id", "usage_monthly", ["id"])
    op.create_index("ix_usage_monthly_organization_id", "usage_monthly", ["organization_id"])
    op.create_index("ix_usage_monthly_period", "usage_monthly", ["period"])

    op.create_table(
        "subscription_requests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("plan_id", sa.String(length=20), sa.ForeignKey("plans.id"), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("contact_name", sa.String(length=255), nullable=False),
        sa.Column("contact_email", sa.String(length=100), nullable=False),
        sa.Column("contact_phone", sa.String(length=20), nullable=False),
        sa.Column("tax_code", sa.String(length=30), nullable=True),
        sa.Column("billing_address", sa.String(length=255), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=True),
        sa.Column("quoted_price_per_seat_vnd", sa.Integer(), nullable=False),
        sa.Column("quoted_monthly_total_vnd", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("reviewed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_subscription_requests_id", "subscription_requests", ["id"])
    op.create_index("ix_subscription_requests_plan_id", "subscription_requests", ["plan_id"])
    op.create_index("ix_subscription_requests_contact_email", "subscription_requests", ["contact_email"])
    op.create_index("ix_subscription_requests_status", "subscription_requests", ["status"])
    op.create_index("ix_subscription_requests_organization_id", "subscription_requests", ["organization_id"])

    plans = sa.table(
        "plans",
        sa.column("id", sa.String()),
        sa.column("name", sa.String()),
        sa.column("description", sa.String()),
        sa.column("price_per_seat_vnd", sa.Integer()),
        sa.column("min_seats", sa.Integer()),
        sa.column("conversations_per_seat", sa.Integer()),
        sa.column("overage_price_vnd", sa.Integer()),
        sa.column("support_note", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime()),
        sa.column("updated_at", sa.DateTime()),
    )
    now = datetime.now(UTC).replace(tzinfo=None)
    op.get_bind().execute(
        sa.insert(plans),
        [{**plan, "is_active": True, "created_at": now, "updated_at": now} for plan in _PLANS],
    )


def downgrade() -> None:
    op.drop_table("subscription_requests")
    op.drop_table("usage_monthly")
    op.drop_table("subscriptions")
    op.drop_table("organization_members")
    op.drop_table("organizations")
    op.drop_table("plans")
