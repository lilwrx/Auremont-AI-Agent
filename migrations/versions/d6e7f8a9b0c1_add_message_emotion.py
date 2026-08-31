"""add message emotion

Cột mới cho phép avatar (AuremontAvatar.tsx) đổi biểu cảm/cử động theo đúng nội dung câu
trả lời của AI — vui khi trả lời tốt, tiếc nuối khi không đủ thông tin/hết hàng, lịch sự
khi cần chuyển giao Sale hoặc từ chối khéo. Tính toán từ tín hiệu pipeline/gate đã có sẵn,
không gọi thêm LLM (xem backend/services/agent_pipeline.py, routers/customer_chat.py).

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("emotion", sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_column("emotion")
