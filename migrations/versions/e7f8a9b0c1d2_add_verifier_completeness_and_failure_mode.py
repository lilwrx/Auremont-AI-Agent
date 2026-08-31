"""add verifier completeness and failure_mode

Hai cột phục vụ Admin Tab 2 (Đánh giá AI). `completeness` là tiêu chí chấm điểm thứ ba
bên cạnh faithfulness/relevancy — câu hỏi nhiều ý mà chỉ trả lời một ý thì hai tiêu chí
kia vẫn cao trong khi câu trả lời thực tế chưa dùng được. `failure_mode` phân loại
nguyên nhân trượt (bịa số liệu / thiếu ý / lệch câu hỏi / ngữ cảnh không có dữ liệu /
cam kết không có căn cứ), để Admin lọc theo nguyên nhân thay vì nhìn một danh sách điểm
thấp không phân biệt được — "model bịa số" và "kho tài liệu thiếu file" cần hai cách xử
lý hoàn toàn khác nhau.

Cả hai đều nullable: các dòng ghi trước khi có cột này, các câu trả lời lấy từ cache, và
mọi thông báo edge-case (empty state, mất kết nối tồn kho) đều không chạy qua Verifier.

Xem backend/services/verifier_service.py.

Revision ID: e7f8a9b0c1d2
Revises: d6e7f8a9b0c1
Create Date: 2026-08-19

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | Sequence[str] | None = "d6e7f8a9b0c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.add_column(sa.Column("completeness", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("failure_mode", sa.String(length=32), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("messages") as batch_op:
        batch_op.drop_column("failure_mode")
        batch_op.drop_column("completeness")
