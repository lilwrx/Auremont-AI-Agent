"""add durable observability metrics

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | Sequence[str] | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pipeline_trace_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("duration_ms", sa.Float(), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("clearance", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("verifier_score", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_pipeline_trace_runs_id", "pipeline_trace_runs", ["id"])
    op.create_index("ix_pipeline_trace_runs_run_id", "pipeline_trace_runs", ["run_id"], unique=True)
    op.create_index("ix_pipeline_trace_runs_started_at", "pipeline_trace_runs", ["started_at"])
    op.create_index("ix_pipeline_trace_runs_project_id", "pipeline_trace_runs", ["project_id"])
    op.create_index("ix_pipeline_trace_runs_outcome", "pipeline_trace_runs", ["outcome"])
    op.create_index("ix_pipeline_trace_runs_created_at", "pipeline_trace_runs", ["created_at"])

    op.create_table(
        "llm_usage_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("usage_id", sa.String(length=32), nullable=False),
        sa.Column("run_id", sa.String(length=32), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_llm_usage_events_id", "llm_usage_events", ["id"])
    op.create_index("ix_llm_usage_events_usage_id", "llm_usage_events", ["usage_id"], unique=True)
    op.create_index("ix_llm_usage_events_run_id", "llm_usage_events", ["run_id"])
    op.create_index("ix_llm_usage_events_request_id", "llm_usage_events", ["request_id"])
    op.create_index("ix_llm_usage_events_operation", "llm_usage_events", ["operation"])
    op.create_index("ix_llm_usage_events_created_at", "llm_usage_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_llm_usage_events_created_at", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_operation", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_request_id", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_run_id", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_usage_id", table_name="llm_usage_events")
    op.drop_index("ix_llm_usage_events_id", table_name="llm_usage_events")
    op.drop_table("llm_usage_events")

    op.drop_index("ix_pipeline_trace_runs_created_at", table_name="pipeline_trace_runs")
    op.drop_index("ix_pipeline_trace_runs_outcome", table_name="pipeline_trace_runs")
    op.drop_index("ix_pipeline_trace_runs_project_id", table_name="pipeline_trace_runs")
    op.drop_index("ix_pipeline_trace_runs_started_at", table_name="pipeline_trace_runs")
    op.drop_index("ix_pipeline_trace_runs_run_id", table_name="pipeline_trace_runs")
    op.drop_index("ix_pipeline_trace_runs_id", table_name="pipeline_trace_runs")
    op.drop_table("pipeline_trace_runs")
