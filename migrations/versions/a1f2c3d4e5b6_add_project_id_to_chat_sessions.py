"""add project_id to chat_sessions

Phiên tư vấn cần biết nó thuộc dự án nào: Agent Pipeline dùng `project_id` để tra
tồn kho real-time (`lookup_inventory` bắt buộc có tham số này) và để lọc tài liệu
đúng dự án khi retrieve từ Qdrant.

Nullable vì các phiên tạo trước migration này không có giá trị, và Sale vẫn có thể
mở phiên hỏi những câu chung không gắn dự án nào.

Revision ID: a1f2c3d4e5b6
Revises: df3813c946cc
Create Date: 2026-08-07

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'a1f2c3d4e5b6'
down_revision: str | Sequence[str] | None = 'df3813c946cc'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    Dùng `batch_alter_table` vì SQLite không hỗ trợ ALTER để thêm constraint
    (`tests/test_migrations.py` chạy migration trên SQLite). Batch mode dựng bảng
    mới rồi copy dữ liệu sang; trên MySQL nó chạy ALTER thẳng như bình thường.
    """
    with op.batch_alter_table('chat_sessions') as batch_op:
        batch_op.add_column(sa.Column('project_id', sa.String(length=36), nullable=True))
        batch_op.create_index(batch_op.f('ix_chat_sessions_project_id'), ['project_id'], unique=False)
        batch_op.create_foreign_key(
            'fk_chat_sessions_project_id_projects', 'projects', ['project_id'], ['id']
        )


def downgrade() -> None:
    """Downgrade schema.

    Bỏ FK trước rồi mới bỏ cột. Không gọi `drop_index` cho index của cột này —
    MySQL báo lỗi 1553 khi index đang được FK dùng, và drop cột sẽ tự dọn index.
    Đây là cùng convention với migration baseline.
    """
    with op.batch_alter_table('chat_sessions') as batch_op:
        batch_op.drop_constraint('fk_chat_sessions_project_id_projects', type_='foreignkey')
        batch_op.drop_column('project_id')
