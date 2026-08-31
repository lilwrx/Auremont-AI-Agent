"""merge audit logs and document classification heads

Revision ID: e1f2a3b4c5d6
Revises: c9d0e1f2a3b4, d9e0f1a2b3c4
Create Date: 2026-08-14

"""

from collections.abc import Sequence


revision: str = "e1f2a3b4c5d6"
down_revision: str | Sequence[str] | None = (
    "c9d0e1f2a3b4",
    "d9e0f1a2b3c4",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join independent migration branches; schema changes are in the parents."""


def downgrade() -> None:
    """Split back to the parent revisions without changing schema."""
