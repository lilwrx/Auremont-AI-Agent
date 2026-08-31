"""add images column to messages

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-08-14

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "f2a3b4c5d6e7"
down_revision: str | Sequence[str] | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Gallery photos shown under an answer. Nullable: every message written before this
    column existed has none, and answers about no particular project still have none."""
    op.add_column("messages", sa.Column("images", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "images")
