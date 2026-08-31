"""add message suggested_questions

Cột mới lưu 2-3 câu hỏi gợi ý tiếp theo mà AI đề xuất sau mỗi câu trả lời (vd. "Giá căn 2PN
bao nhiêu?"), dựa trên chủ đề đang trao đổi trong phiên chat. Khác với `quick_replies`
(chỉ luồng khách, là lựa chọn TRẢ LỜI cho câu AI vừa hỏi), cột này áp dụng cho CẢ Sale lẫn
khách và là câu hỏi MỚI người dùng có thể muốn hỏi tiếp.

Sinh trong cùng một lời gọi LLM với câu trả lời (schema-constrained decoding), không tốn
thêm round trip. Xem backend/ai/prompts.py::ConsultAnswer / SaleAnswer và
backend/services/agent_pipeline.py::_generate.

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-08-21

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a2b3c4d5e6f7"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("suggested_questions", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_column("suggested_questions")
