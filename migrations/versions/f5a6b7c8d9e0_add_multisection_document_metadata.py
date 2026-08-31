"""add multi-section document classification metadata

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5a6b7c8d9e0"
down_revision: str | Sequence[str] | None = "e4f5a6b7c8d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("categories", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("section_classifications", sa.JSON(), nullable=True))

    documents = sa.table(
        "documents",
        sa.column("id", sa.Integer()),
        sa.column("category", sa.String(length=50)),
        sa.column("categories", sa.JSON()),
        sa.column("section_classifications", sa.JSON()),
    )
    connection = op.get_bind()
    rows = connection.execute(sa.select(documents.c.id, documents.c.category)).all()
    for document_id, category in rows:
        primary = category or "other"
        connection.execute(
            sa.update(documents)
            .where(documents.c.id == document_id)
            .values(categories=[primary], section_classifications=[])
        )


def downgrade() -> None:
    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_column("section_classifications")
        batch_op.drop_column("categories")
