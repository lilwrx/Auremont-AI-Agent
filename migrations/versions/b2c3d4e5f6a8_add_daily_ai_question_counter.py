"""add the per-session daily AI question counter

Held on `chat_sessions` rather than derived from `messages`, because clearing a transcript
("Xoá lịch sử") deletes the messages and keeps the session row — a message-derived count
would hand the visitor a fresh allowance on every clear.

Revision ID: b2c3d4e5f6a8
Revises: a1b2c3d4e5f6
Create Date: 2026-08-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a8"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(sa.Column("ai_questions_today", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("ai_questions_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("ai_questions_date")
        batch_op.drop_column("ai_questions_today")
