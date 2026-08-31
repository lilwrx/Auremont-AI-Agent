"""add details json column to projects

Revision ID: 75d066960334
Revises: b7c8d9e0f1a2
Create Date: 2026-08-08 15:12:35.769841

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = '75d066960334'
down_revision: str | Sequence[str] | None = 'b7c8d9e0f1a2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('projects', sa.Column('details', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('projects', 'details')
