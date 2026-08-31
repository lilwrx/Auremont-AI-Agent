"""add official website news articles

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | Sequence[str] | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url_hash", sa.String(length=64), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("source_id", sa.String(length=50), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("topic", sa.String(length=50), nullable=False),
        sa.Column("project_names", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_news_articles_id", "news_articles", ["id"])
    op.create_index("ix_news_articles_url_hash", "news_articles", ["url_hash"], unique=True)
    op.create_index("ix_news_articles_source_id", "news_articles", ["source_id"])
    op.create_index("ix_news_articles_topic", "news_articles", ["topic"])
    op.create_index("ix_news_articles_status", "news_articles", ["status"])
    op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"])
    op.create_index("ix_news_articles_expires_at", "news_articles", ["expires_at"])
    op.create_index("ix_news_articles_archived_at", "news_articles", ["archived_at"])


def downgrade() -> None:
    op.drop_index("ix_news_articles_archived_at", table_name="news_articles")
    op.drop_index("ix_news_articles_expires_at", table_name="news_articles")
    op.drop_index("ix_news_articles_published_at", table_name="news_articles")
    op.drop_index("ix_news_articles_status", table_name="news_articles")
    op.drop_index("ix_news_articles_topic", table_name="news_articles")
    op.drop_index("ix_news_articles_source_id", table_name="news_articles")
    op.drop_index("ix_news_articles_url_hash", table_name="news_articles")
    op.drop_index("ix_news_articles_id", table_name="news_articles")
    op.drop_table("news_articles")
