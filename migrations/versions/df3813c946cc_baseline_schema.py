"""baseline schema

Toàn bộ 8 bảng của SalesMate: users, projects, documents, chat_sessions,
messages, feedback, hitl_logs (audit trail HITL), conflict_flags.

Đây là ảnh chụp schema tại thời điểm dự án chuyển từ `Base.metadata.create_all`
sang Alembic. DB nào đã có sẵn các bảng này thì đánh dấu bằng
`alembic stamp df3813c946cc` thay vì chạy upgrade.

Revision ID: df3813c946cc
Revises:
Create Date: 2026-08-03 16:20:51.564246

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = 'df3813c946cc'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('projects',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('location', sa.String(length=255), nullable=True),
    sa.Column('description', sa.String(length=2000), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_projects_id'), 'projects', ['id'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('username', sa.String(length=50), nullable=False),
    sa.Column('email', sa.String(length=100), nullable=False),
    sa.Column('hashed_password', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('permissions', sa.JSON(), nullable=True),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_username'), 'users', ['username'], unique=True)
    op.create_table('chat_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('sale_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=True),
    sa.Column('customer_name', sa.String(length=255), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['sale_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_chat_sessions_id'), 'chat_sessions', ['id'], unique=False)
    op.create_index(op.f('ix_chat_sessions_sale_id'), 'chat_sessions', ['sale_id'], unique=False)
    op.create_table('documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.String(length=36), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('file_path', sa.String(length=512), nullable=True),
    sa.Column('status', sa.String(length=50), nullable=False),
    sa.Column('visibility', sa.String(length=20), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('uploaded_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['uploaded_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_documents_id'), 'documents', ['id'], unique=False)
    op.create_index(op.f('ix_documents_project_id'), 'documents', ['project_id'], unique=False)
    op.create_index(op.f('ix_documents_uploaded_by'), 'documents', ['uploaded_by'], unique=False)
    op.create_table('conflict_flags',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('document_id_a', sa.Integer(), nullable=False),
    sa.Column('document_id_b', sa.Integer(), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('resolved_by', sa.Integer(), nullable=True),
    sa.Column('resolved_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['document_id_a'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['document_id_b'], ['documents.id'], ),
    sa.ForeignKeyConstraint(['resolved_by'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conflict_flags_document_id_a'), 'conflict_flags', ['document_id_a'], unique=False)
    op.create_index(op.f('ix_conflict_flags_document_id_b'), 'conflict_flags', ['document_id_b'], unique=False)
    op.create_index(op.f('ix_conflict_flags_id'), 'conflict_flags', ['id'], unique=False)
    op.create_index(op.f('ix_conflict_flags_resolved_by'), 'conflict_flags', ['resolved_by'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('session_id', sa.Integer(), nullable=True),
    sa.Column('sender', sa.String(length=20), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('citations', sa.JSON(), nullable=True),
    sa.Column('verifier_score', sa.Float(), nullable=True),
    sa.Column('requires_hitl', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['session_id'], ['chat_sessions.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_id'), 'messages', ['id'], unique=False)
    op.create_index(op.f('ix_messages_session_id'), 'messages', ['session_id'], unique=False)
    op.create_table('feedback',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_feedback_id'), 'feedback', ['id'], unique=False)
    op.create_index(op.f('ix_feedback_message_id'), 'feedback', ['message_id'], unique=False)
    op.create_index(op.f('ix_feedback_type'), 'feedback', ['type'], unique=False)
    op.create_index(op.f('ix_feedback_user_id'), 'feedback', ['user_id'], unique=False)
    op.create_table('hitl_logs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('message_id', sa.Integer(), nullable=False),
    sa.Column('sale_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('confirmed_content', sa.Text(), nullable=True),
    sa.Column('confirmed_at', sa.DateTime(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ),
    sa.ForeignKeyConstraint(['sale_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_hitl_logs_id'), 'hitl_logs', ['id'], unique=False)
    op.create_index(op.f('ix_hitl_logs_message_id'), 'hitl_logs', ['message_id'], unique=False)
    op.create_index(op.f('ix_hitl_logs_sale_id'), 'hitl_logs', ['sale_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema.

    Đã bỏ các lệnh `op.drop_index` mà autogenerate sinh ra: MySQL từ chối xoá
    index đang phục vụ một khoá ngoại (lỗi 1553), và `drop_table` vốn đã xoá
    index của chính bảng đó. Thứ tự drop đi ngược chiều phụ thuộc khoá ngoại.
    """
    op.drop_table('hitl_logs')
    op.drop_table('feedback')
    op.drop_table('messages')
    op.drop_table('conflict_flags')
    op.drop_table('documents')
    op.drop_table('chat_sessions')
    op.drop_table('users')
    op.drop_table('projects')
