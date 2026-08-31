"""add document classification provenance

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "b3c4d5e6f7a8"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Persist the LLM review signal and server-owned classifier version."""

    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("classification_requires_admin_review", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("classification_version", sa.String(length=30), nullable=True))
        batch_op.create_index(
            "ix_documents_classification_version",
            ["classification_version"],
            unique=False,
        )


def downgrade() -> None:
    """Remove classifier provenance fields."""

    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index("ix_documents_classification_version")
        batch_op.drop_column("classification_version")
        batch_op.drop_column("classification_requires_admin_review")
