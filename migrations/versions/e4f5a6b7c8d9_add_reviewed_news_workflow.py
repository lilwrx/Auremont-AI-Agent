"""add Sale-authored and Admin-reviewed news workflow

Revision ID: e4f5a6b7c8d9
Revises: e8f9a0b1c2d3
Create Date: 2026-08-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4f5a6b7c8d9"
down_revision: str | Sequence[str] | None = "e8f9a0b1c2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("news_articles") as batch_op:
        batch_op.add_column(sa.Column("content", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("author_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reviewer_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("review_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("submitted_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            "fk_news_articles_author_id_users",
            "users",
            ["author_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_news_articles_reviewer_id_users",
            "users",
            ["reviewer_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_news_articles_author_id", ["author_id"])
        batch_op.create_index("ix_news_articles_reviewer_id", ["reviewer_id"])
        batch_op.create_index("ix_news_articles_submitted_at", ["submitted_at"])


def downgrade() -> None:
    with op.batch_alter_table("news_articles") as batch_op:
        batch_op.drop_index("ix_news_articles_submitted_at")
        batch_op.drop_index("ix_news_articles_reviewer_id")
        batch_op.drop_index("ix_news_articles_author_id")
        batch_op.drop_constraint("fk_news_articles_reviewer_id_users", type_="foreignkey")
        batch_op.drop_constraint("fk_news_articles_author_id_users", type_="foreignkey")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("submitted_at")
        batch_op.drop_column("review_note")
        batch_op.drop_column("reviewer_id")
        batch_op.drop_column("author_id")
        batch_op.drop_column("content")
