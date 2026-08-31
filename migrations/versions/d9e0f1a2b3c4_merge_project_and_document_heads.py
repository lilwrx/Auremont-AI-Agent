"""merge project details and document classification heads

Revision ID: d9e0f1a2b3c4
Revises: 75d066960334, c8d9e0f1a2b3
Create Date: 2026-08-14

"""

from collections.abc import Sequence


revision: str = "d9e0f1a2b3c4"
down_revision: str | Sequence[str] | None = (
    "75d066960334",
    "c8d9e0f1a2b3",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Join independent migration branches; schema changes are in the parents."""


def downgrade() -> None:
    """Split back to the parent revisions without changing schema."""
