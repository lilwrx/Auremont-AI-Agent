"""add faithfulness and answer_relevancy to messages

Tab 2 của Admin (Đánh giá & Phân tích AI) hiển thị Faithfulness và Answer Relevancy
thành hai ô riêng, nhưng `messages.verifier_score` chỉ lưu `min(faithfulness, relevancy)`
— không thể tách ngược một số thành hai. Hai cột này giữ lại điểm thành phần do
Verifier Agent chấm.

Tách riêng vì hai chỉ số chẩn đoán hai vấn đề khác nhau: faithfulness thấp nghĩa là
model bịa số liệu (sửa prompt/verifier), relevancy thấp nghĩa là retrieval lấy sai
tài liệu (sửa chunking/ingest).

Nullable: các message ghi trước migration này không có giá trị, và cả những message
không hề chạy qua Verifier (cache hit, các notice edge-case như empty state hay mất
kết nối API tồn kho).

Revision ID: b7c8d9e0f1a2
Revises: a1f2c3d4e5b6
Create Date: 2026-08-09

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'b7c8d9e0f1a2'
down_revision: str | Sequence[str] | None = 'a1f2c3d4e5b6'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Dùng `batch_alter_table` theo đúng convention của các migration trước: SQLite
    (dùng trong tests/test_migrations.py) không hỗ trợ ALTER đầy đủ, còn trên MySQL
    batch mode chạy ALTER thẳng như bình thường.
    """
    with op.batch_alter_table('messages') as batch_op:
        batch_op.add_column(sa.Column('faithfulness', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('answer_relevancy', sa.Float(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('messages') as batch_op:
        batch_op.drop_column('answer_relevancy')
        batch_op.drop_column('faithfulness')
