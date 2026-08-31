"""add message quick_replies

Cột mới cho phép AI (khi tư vấn khách qua SYSTEM_INSTRUCTION_PUBLIC) đính kèm 2-4 lựa chọn
trả lời ngắn cho câu hỏi khảo sát nhu cầu vừa đặt ra (vd. "Để ở"/"Đầu tư"), để khách bấm
chọn thay vì phải gõ. Model tự quyết định có option hay không theo từng câu hỏi — không có
bộ option cố định nào ở tầng backend. Xem backend/ai/prompts.py::ConsultAnswer và
backend/services/agent_pipeline.py.

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e7f8a9b0c1d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("quick_replies", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_column("quick_replies")
