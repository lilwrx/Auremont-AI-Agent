"""add chat session status

Cột `status` cho phép AI tự nhận biết khi nào phải im lặng nhường lời cho Sale: một
session khách (anonymous/CUSTOMER) chuyển từ BOT_HANDLING sang WAITING_SALE khi cần
người thật, rồi SALE_HANDLING khi một Sale bấm "Tiếp nhận". Session của Sale tự tư vấn
(sale_id-only) không dùng tới cột này, giữ mặc định.

Revision ID: b4c5d6e7f8a9
Revises: a3b4c5d6e7f8
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4c5d6e7f8a9"
down_revision: str | Sequence[str] | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    `batch_alter_table` vì SQLite không hỗ trợ ALTER thêm cột NOT NULL kèm server_default
    trực tiếp (`tests/test_migrations.py` chạy migration trên SQLite) — cùng convention
    với các migration trước.
    """
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(
            sa.Column("status", sa.String(length=20), nullable=False, server_default="bot_handling")
        )


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("status")
