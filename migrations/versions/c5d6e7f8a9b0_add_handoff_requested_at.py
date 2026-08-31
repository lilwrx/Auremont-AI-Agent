"""add handoff_requested_at to chat_sessions

Hàng chờ "Khách đang chờ" (live-inbox) trước đây tính thời gian chờ từ `created_at` của
session — sai, vì một session có thể được tạo từ rất lâu trước lúc thực sự cần người thật
(khách chat với AI một hồi rồi mới yêu cầu). Cột mới này chỉ được ghi đúng lúc session
chuyển sang WAITING_SALE (xem repositories/chat_session.py::enter_waiting_queue), nên phản
ánh đúng "chờ từ lúc nào".

Revision ID: c5d6e7f8a9b0
Revises: b4c5d6e7f8a9
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b4c5d6e7f8a9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.add_column(sa.Column("handoff_requested_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_column("handoff_requested_at")
