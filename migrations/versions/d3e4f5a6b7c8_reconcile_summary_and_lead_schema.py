"""reconcile the customer-summary and lead migration histories

The feature branch and ``develop`` both shipped revision ``b1c2d3e4f5a6`` but with
different schema changes.  A database upgraded on either branch therefore records the
same Alembic revision while it may contain only one of the two feature sets.  This
revision converges both histories by inspecting the actual schema and creating only the
missing objects.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3e4f5a6b7c8"
down_revision: str | Sequence[str] | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _column_names(table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def _ensure_index(name: str, table_name: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _index_names(table_name):
        op.create_index(name, table_name, columns, unique=unique)


def _ensure_customer_summaries() -> None:
    if "customer_conversation_summaries" not in _table_names():
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
    _ensure_index(
        "ix_customer_conversation_summaries_id",
        "customer_conversation_summaries",
        ["id"],
    )


def _ensure_leads() -> None:
    if "leads" not in _table_names():
        op.create_table(
            "leads",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("customer_id", sa.Integer(), nullable=True),
            sa.Column("visitor_token", sa.String(length=64), nullable=True),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("tier", sa.String(length=10), nullable=False, server_default="cold"),
            sa.Column("score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("rule_score", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("soft_score", sa.Integer(), nullable=True),
            sa.Column("urgency", sa.String(length=12), nullable=True),
            sa.Column("purpose", sa.String(length=20), nullable=True),
            sa.Column("signals", sa.JSON(), nullable=True),
            sa.Column("detection_method", sa.String(length=20), nullable=False, server_default="rule"),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("analysis_version", sa.String(length=20), nullable=True),
            sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("llm_scored_turn", sa.Integer(), nullable=True),
            sa.Column("scored_at", sa.DateTime(), nullable=True),
            sa.Column("llm_scored_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
            sa.PrimaryKeyConstraint("id"),
        )

    _ensure_index("ix_leads_id", "leads", ["id"])
    _ensure_index("ix_leads_customer_id", "leads", ["customer_id"], unique=True)
    _ensure_index("ix_leads_visitor_token", "leads", ["visitor_token"], unique=True)
    _ensure_index("ix_leads_project_id", "leads", ["project_id"])
    _ensure_index("ix_leads_tier", "leads", ["tier"])
    _ensure_index("ix_leads_scored_at", "leads", ["scored_at"])


def _ensure_user_contact_columns() -> None:
    columns = _column_names("users")
    with op.batch_alter_table("users") as batch_op:
        if "full_name" not in columns:
            batch_op.add_column(sa.Column("full_name", sa.String(length=255), nullable=True))
        if "phone" not in columns:
            batch_op.add_column(sa.Column("phone", sa.String(length=20), nullable=True))

    _ensure_index("ix_users_phone", "users", ["phone"])


def upgrade() -> None:
    _ensure_customer_summaries()
    _ensure_leads()
    _ensure_user_contact_columns()


def downgrade() -> None:
    pass
