"""add document current flag

Revision ID: c8d9e0f1a2b3
Revises: 116684884a56
Create Date: 2026-08-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c8d9e0f1a2b3"
down_revision: str | Sequence[str] | None = "116684884a56"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(
            sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true())
        )
        batch_op.create_index("ix_documents_is_current", ["is_current"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index("ix_documents_is_current")
        batch_op.drop_column("is_current")
