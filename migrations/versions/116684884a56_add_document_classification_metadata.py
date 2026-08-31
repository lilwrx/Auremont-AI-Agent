"""add document classification metadata

Revision ID: 116684884a56
Revises: b7c8d9e0f1a2
Create Date: 2026-08-13 12:43:21.564368
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "116684884a56"
down_revision: str | Sequence[str] | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add project-document classification fields and document relationships."""
    with op.batch_alter_table("documents") as batch_op:
        batch_op.add_column(sa.Column("subdivision_names", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("building_codes", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("unit_types", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("applicable_area", sa.String(length=255), nullable=True))
        batch_op.add_column(
            sa.Column(
                "category",
                sa.String(length=50),
                nullable=False,
                server_default="other",
            )
        )
        batch_op.add_column(sa.Column("subcategory", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("document_summary", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "review_status",
                sa.String(length=30),
                nullable=False,
                server_default="pending",
            )
        )
        batch_op.add_column(sa.Column("classification_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("classification_reason", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("classified_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("reviewed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("version_label", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("issued_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("effective_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("expiry_date", sa.Date(), nullable=True))
        batch_op.add_column(sa.Column("applicable_period", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("legal_document_type", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("legal_document_number", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("legal_issuer", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("legal_domain", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column(
                "legal_status",
                sa.String(length=30),
                nullable=False,
                server_default="unknown",
            )
        )
        batch_op.create_foreign_key(
            "fk_documents_reviewed_by_users",
            "users",
            ["reviewed_by"],
            ["id"],
        )
        batch_op.create_index("ix_documents_category", ["category"], unique=False)
        batch_op.create_index("ix_documents_status", ["status"], unique=False)
        batch_op.create_index("ix_documents_subcategory", ["subcategory"], unique=False)
        batch_op.create_index("ix_documents_visibility", ["visibility"], unique=False)
        batch_op.create_index("ix_documents_review_status", ["review_status"], unique=False)
        batch_op.create_index("ix_documents_reviewed_by", ["reviewed_by"], unique=False)
        batch_op.create_index("ix_documents_legal_document_type", ["legal_document_type"], unique=False)
        batch_op.create_index("ix_documents_legal_document_number", ["legal_document_number"], unique=False)
        batch_op.create_index("ix_documents_legal_domain", ["legal_domain"], unique=False)
        batch_op.create_index("ix_documents_legal_status", ["legal_status"], unique=False)

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
    op.create_index("ix_document_relations_id", "document_relations", ["id"], unique=False)
    op.create_index("ix_document_relations_source_document_id", "document_relations", ["source_document_id"], unique=False)
    op.create_index("ix_document_relations_target_document_id", "document_relations", ["target_document_id"], unique=False)
    op.create_index("ix_document_relations_relation_type", "document_relations", ["relation_type"], unique=False)
    op.create_index("ix_document_relations_review_status", "document_relations", ["review_status"], unique=False)
    op.create_index("ix_document_relations_reviewed_by", "document_relations", ["reviewed_by"], unique=False)


def downgrade() -> None:
    """Remove classification data in reverse dependency order."""
    op.drop_index("ix_document_relations_reviewed_by", table_name="document_relations")
    op.drop_index("ix_document_relations_review_status", table_name="document_relations")
    op.drop_index("ix_document_relations_relation_type", table_name="document_relations")
    op.drop_index("ix_document_relations_target_document_id", table_name="document_relations")
    op.drop_index("ix_document_relations_source_document_id", table_name="document_relations")
    op.drop_index("ix_document_relations_id", table_name="document_relations")
    op.drop_table("document_relations")

    with op.batch_alter_table("documents") as batch_op:
        batch_op.drop_index("ix_documents_visibility")
        batch_op.drop_index("ix_documents_legal_status")
        batch_op.drop_index("ix_documents_legal_domain")
        batch_op.drop_index("ix_documents_legal_document_number")
        batch_op.drop_index("ix_documents_legal_document_type")
        batch_op.drop_index("ix_documents_reviewed_by")
        batch_op.drop_index("ix_documents_review_status")
        batch_op.drop_index("ix_documents_subcategory")
        batch_op.drop_index("ix_documents_status")
        batch_op.drop_index("ix_documents_category")
        batch_op.drop_constraint("fk_documents_reviewed_by_users", type_="foreignkey")
        batch_op.drop_column("legal_status")
        batch_op.drop_column("legal_domain")
        batch_op.drop_column("legal_issuer")
        batch_op.drop_column("legal_document_number")
        batch_op.drop_column("legal_document_type")
        batch_op.drop_column("applicable_period")
        batch_op.drop_column("expiry_date")
        batch_op.drop_column("effective_date")
        batch_op.drop_column("issued_date")
        batch_op.drop_column("version_label")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("reviewed_by")
        batch_op.drop_column("classified_at")
        batch_op.drop_column("classification_reason")
        batch_op.drop_column("classification_confidence")
        batch_op.drop_column("review_status")
        batch_op.drop_column("document_summary")
        batch_op.drop_column("subcategory")
        batch_op.drop_column("category")
        batch_op.drop_column("applicable_area")
        batch_op.drop_column("unit_types")
        batch_op.drop_column("building_codes")
        batch_op.drop_column("subdivision_names")
