"""add listings column to messages

Revision ID: f3a4b5c6d7e8
Revises: a2b3c4d5e6f7
Create Date: 2026-08-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a4b5c6d7e8"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Recommended units rendered as their own cards. Nullable: every message written
    before this column existed has none, and an answer that names no specific unit still
    has none."""
    op.add_column("messages", sa.Column("listings", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("messages", "listings")
