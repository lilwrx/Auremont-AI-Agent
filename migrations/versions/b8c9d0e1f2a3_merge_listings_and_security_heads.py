"""merge message listings and security/observability heads

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2, f3a4b5c6d7e8
Create Date: 2026-08-23

"""

from collections.abc import Sequence


revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = (
    "a7b8c9d0e1f2",
    "f3a4b5c6d7e8",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join independent migration branches; schema changes are in the parents."""


def downgrade() -> None:
    """Split back to the parent revisions without changing schema."""
