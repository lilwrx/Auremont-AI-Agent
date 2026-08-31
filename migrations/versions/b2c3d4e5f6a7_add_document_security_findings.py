"""add document security findings

Revision ID: b2c3d4e5f6a7
Revises: a2b3c4d5e6f7
Create Date: 2026-08-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a2b3c4d5e6f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("block_reason", sa.String(length=50), nullable=True))
    op.add_column("documents", sa.Column("security_findings", sa.JSON(), nullable=True))
    op.create_index(op.f("ix_documents_block_reason"), "documents", ["block_reason"], unique=False)
    op.execute(
        sa.text("UPDATE documents SET block_reason = 'legacy_unknown' WHERE status = 'blocked'")
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_documents_block_reason"), table_name="documents")
    op.drop_column("documents", "security_findings")
    op.drop_column("documents", "block_reason")
