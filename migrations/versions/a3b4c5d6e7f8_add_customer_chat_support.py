"""add customer chat support

Thêm role Customer: khách hàng ghé thăm công khai (không cần đăng nhập) có thể chat với
AI, giới hạn ở dữ liệu PUBLIC-tier. `chat_sessions` giờ phục vụ cả 3 kiểu owner — xem
docstring của model `ChatSession` để biết bất biến (đúng 1 trong 3 cột được set).

`sale_id` chuyển nullable vì một session customer/anonymous không có Sale sở hữu; mọi
query Sale hiện tại đều lọc `WHERE sale_id = :user.id` nên không ảnh hưởng dữ liệu cũ.

Revision ID: a3b4c5d6e7f8
Revises: f2a3b4c5d6e7
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | Sequence[str] | None = "f2a3b4c5d6e7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema.

    `batch_alter_table` vì SQLite không hỗ trợ ALTER để đổi nullable/thêm constraint
    (`tests/test_migrations.py` chạy migration trên SQLite) — cùng convention với
    a1f2c3d4e5b6_add_project_id_to_chat_sessions.py.
    """
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.alter_column("sale_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("customer_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("visitor_token", sa.String(length=64), nullable=True))
        batch_op.create_index(batch_op.f("ix_chat_sessions_customer_id"), ["customer_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_chat_sessions_visitor_token"), ["visitor_token"], unique=True
        )
        batch_op.create_foreign_key(
            "fk_chat_sessions_customer_id_users", "users", ["customer_id"], ["id"]
        )


def downgrade() -> None:
    """Downgrade schema.

    Bỏ FK trước rồi mới bỏ cột, không tự drop_index cho customer_id (index đang được FK
    dùng — MySQL báo lỗi 1553; drop cột sẽ tự dọn). visitor_token không có FK nên index
    của nó được bỏ tường minh.
    """
    with op.batch_alter_table("chat_sessions") as batch_op:
        batch_op.drop_constraint("fk_chat_sessions_customer_id_users", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_chat_sessions_visitor_token"))
        batch_op.drop_column("visitor_token")
        batch_op.drop_column("customer_id")
        batch_op.alter_column("sale_id", existing_type=sa.Integer(), nullable=False)
