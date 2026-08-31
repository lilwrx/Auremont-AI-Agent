"""repair a missing document_relations table

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-08-22

Some long-lived development databases were stamped past the original classification
migration while ``document_relations`` was absent.  A fresh database is already correct,
so this revision is deliberately idempotent: it creates only the missing table/indexes.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "c4d5e6f7a8b9"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_INDEXES: dict[str, list[str]] = {
    "ix_document_relations_id": ["id"],
    "ix_document_relations_source_document_id": ["source_document_id"],
    "ix_document_relations_target_document_id": ["target_document_id"],
    "ix_document_relations_relation_type": ["relation_type"],
    "ix_document_relations_review_status": ["review_status"],
    "ix_document_relations_reviewed_by": ["reviewed_by"],
}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("document_relations"):
        op.create_table(
            "document_relations",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("source_document_id", sa.Integer(), nullable=False),
            sa.Column("target_document_id", sa.Integer(), nullable=False),
            sa.Column("relation_type", sa.String(length=30), nullable=False),
            sa.Column("scope_note", sa.Text(), nullable=True),
            sa.Column("evidence", sa.Text(), nullable=True),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("review_status", sa.String(length=30), nullable=False),
            sa.Column("reviewed_by", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
            sa.ForeignKeyConstraint(["source_document_id"], ["documents.id"]),
            sa.ForeignKeyConstraint(["target_document_id"], ["documents.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        existing_indexes: set[str] = set()
    else:
        existing_indexes = {index["name"] for index in inspector.get_indexes("document_relations")}

    for index_name, columns in _INDEXES.items():
        if index_name not in existing_indexes:
            op.create_index(index_name, "document_relations", columns, unique=False)


def downgrade() -> None:
    pass
