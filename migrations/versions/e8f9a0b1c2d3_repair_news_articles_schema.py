"""repair news articles schema for databases affected by the duplicate revision

Revision ID: e8f9a0b1c2d3
Revises: d3e4f5a6b7c8
Create Date: 2026-08-28

Some databases recorded ``c2d3e4f5a6b7`` while the duplicate revision bearing that
identifier was applied.  As a result, Alembic considered the official-news migration
complete even though ``news_articles`` had never been created.  This revision repairs
that state without changing healthy databases.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: str | Sequence[str] | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _table_names() -> set[str]:
    return set(sa.inspect(op.get_bind()).get_table_names())


def _index_names(table_name: str) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
        if index.get("name")
    }


def _ensure_index(name: str, columns: list[str], *, unique: bool = False) -> None:
    if name not in _index_names("news_articles"):
        op.create_index(name, "news_articles", columns, unique=unique)


def upgrade() -> None:
    if "news_articles" not in _table_names():
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

    _ensure_index("ix_news_articles_id", ["id"])
    _ensure_index("ix_news_articles_url_hash", ["url_hash"], unique=True)
    _ensure_index("ix_news_articles_source_id", ["source_id"])
    _ensure_index("ix_news_articles_topic", ["topic"])
    _ensure_index("ix_news_articles_status", ["status"])
    _ensure_index("ix_news_articles_published_at", ["published_at"])
    _ensure_index("ix_news_articles_expires_at", ["expires_at"])
    _ensure_index("ix_news_articles_archived_at", ["archived_at"])


def downgrade() -> None:
    pass
