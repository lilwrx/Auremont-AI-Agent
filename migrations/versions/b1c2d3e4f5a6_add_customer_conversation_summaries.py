"""add durable incremental customer conversation summaries

Revision ID: b1c2d3e4f5a6
Revises: a1b2c3d4e5f7
Create Date: 2026-08-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "customer_conversation_summaries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("summary_text", sa.Text(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("last_processed_message_id", sa.Integer(), nullable=False),
        sa.Column("source_message_count", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("generated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("customer_id"),
    )
    op.create_index(
        "ix_customer_conversation_summaries_id",
        "customer_conversation_summaries",
        ["id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_customer_conversation_summaries_id",
        table_name="customer_conversation_summaries",
    )
    op.drop_table("customer_conversation_summaries")
