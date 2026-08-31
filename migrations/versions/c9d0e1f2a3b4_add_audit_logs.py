"""add audit_logs table

Log hiện chỉ đổ ra stdout và biến mất khi container bị thay thế. Điều đó đủ để trả
lời "vừa nãy hỏng cái gì", nhưng không trả lời được "ai đăng nhập tuần trước",
"Sale nào đã xác nhận mức giá đó" — vốn là mục đích của một audit trail.

Chỉ các sự kiện nghiệp vụ (`salesmate.audit`) được ghi vào đây. Log chẩn đoán
(traceback, access log) vẫn ở stdout: khối lượng lớn, vòng đời ngắn, và thuộc về
log collector chứ không phải database vận hành.

`user_id` cố ý KHÔNG có ForeignKey: một dòng audit phải sống lâu hơn user mà nó
tham chiếu. Cascade delete xoá sạch dấu vết của một tài khoản vừa bị gỡ sẽ phá
đúng mục đích của việc lưu audit.

`payload` dùng JSON thay vì một bảng rộng đầy cột NULL: mỗi loại sự kiện mang một
shape khác nhau, và thêm field cho một sự kiện không nên kéo theo một migration.

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-08-13

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'c9d0e1f2a3b4'
down_revision: str | Sequence[str] | None = 'b7c8d9e0f1a2'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('event', sa.String(length=64), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('username', sa.String(length=50), nullable=True),
        sa.Column('request_id', sa.String(length=64), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_logs_id'), 'audit_logs', ['id'])
    op.create_index(op.f('ix_audit_logs_event'), 'audit_logs', ['event'])
    op.create_index(op.f('ix_audit_logs_user_id'), 'audit_logs', ['user_id'])
    op.create_index(op.f('ix_audit_logs_created_at'), 'audit_logs', ['created_at'])
    op.create_index(op.f('ix_audit_logs_request_id'), 'audit_logs', ['request_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_audit_logs_request_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_created_at'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_user_id'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_event'), table_name='audit_logs')
    op.drop_index(op.f('ix_audit_logs_id'), table_name='audit_logs')
    op.drop_table('audit_logs')
