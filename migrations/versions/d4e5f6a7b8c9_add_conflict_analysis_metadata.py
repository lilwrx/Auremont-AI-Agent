"""add structured conflict analysis metadata

Revision ID: d4e5f6a7b8c9
Revises: c4d5e6f7a8b9
Create Date: 2026-08-22

The existing description remains the backwards-compatible human summary. Structured
detector provenance and evidence are additive so legacy conflict rows and clients keep
working while semantic LLM analysis can be persisted and audited.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | Sequence[str] | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("conflict_flags") as batch_op:
        batch_op.add_column(
            sa.Column(
                "detection_method",
                sa.String(length=20),
                nullable=False,
                server_default="rule",
            )
        )
        batch_op.add_column(sa.Column("confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("similarity_score", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("conflict_type", sa.String(length=50), nullable=True))
        batch_op.add_column(sa.Column("evidence", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("analysis_version", sa.String(length=100), nullable=True))

    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("conflict_facts", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("conflict_facts")

    with op.batch_alter_table("conflict_flags") as batch_op:
        batch_op.drop_column("analysis_version")
        batch_op.drop_column("evidence")
        batch_op.drop_column("conflict_type")
        batch_op.drop_column("similarity_score")
        batch_op.drop_column("confidence")
        batch_op.drop_column("detection_method")
