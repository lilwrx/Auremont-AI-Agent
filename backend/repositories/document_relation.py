from sqlalchemy.orm import Session

from backend.core.enums import (
    DocumentRelationType,
    DocumentReviewStatus,
    DocumentStatus,
    LegalStatus,
)
from backend.models.document import Document
from backend.models.document_relation import DocumentRelation
from backend.schemas.document_relation import DocumentRelationCreate
from backend.services.vector_store_service import document_vector_metadata_snapshot
from backend.utils.time import utcnow


def create_document_relation(db: Session, payload: DocumentRelationCreate) -> DocumentRelation:
    if payload.source_document_id == payload.target_document_id:
        raise ValueError("A document cannot have a relation with itself.")

    ids = {payload.source_document_id, payload.target_document_id}
    found = {row.id for row in db.query(Document.id).filter(Document.id.in_(ids)).all()}
    if found != ids:
        raise ValueError("One or both documents do not exist.")

    relation = DocumentRelation(**payload.model_dump())
    db.add(relation)
    db.commit()
    db.refresh(relation)
    return relation


def list_document_relations(
    db: Session,
    *,
    pending_only: bool = False,
) -> list[DocumentRelation]:
    query = db.query(DocumentRelation)
    if pending_only:
        query = query.filter(DocumentRelation.review_status == DocumentReviewStatus.PENDING)
    return query.order_by(DocumentRelation.created_at.desc()).all()


def review_document_relation(
    db: Session,
    relation_id: int,
    *,
    approve: bool,
    reviewed_by: int,
    commit: bool = True,
) -> tuple[DocumentRelation, Document | None, dict[str, object] | None]:
    relation = (
        db.query(DocumentRelation)
        .filter(DocumentRelation.id == relation_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
    if relation is None:
        raise ValueError(f"DocumentRelation with id={relation_id} not found.")
    if relation.review_status != DocumentReviewStatus.PENDING:
        raise ValueError("This relation has already been reviewed.")

    relation.review_status = DocumentReviewStatus.APPROVED if approve else DocumentReviewStatus.REJECTED
    relation.reviewed_by = reviewed_by
    relation.reviewed_at = utcnow()

    superseded: Document | None = None
    previous_vector_metadata: dict[str, object] | None = None
    inactive_relations = {
        DocumentRelationType.REPLACES,
        DocumentRelationType.SUPERSEDES,
        DocumentRelationType.REPEALS,
    }
    if approve and relation.relation_type in inactive_relations:
        documents = (
            db.query(Document)
            .filter(Document.id.in_([relation.source_document_id, relation.target_document_id]))
            .order_by(Document.id)
            .populate_existing()
            .with_for_update()
            .all()
        )
        documents_by_id = {document.id: document for document in documents}
        source = documents_by_id.get(relation.source_document_id)
        superseded = documents_by_id.get(relation.target_document_id)
        if source is None or superseded is None:
            raise ValueError("One or both documents in this relation no longer exist.")
        if (
            source.status != DocumentStatus.COMPLETED
            or source.review_status != DocumentReviewStatus.APPROVED
            or not source.is_current
            or source.legal_status
            in {
                LegalStatus.NOT_YET_EFFECTIVE,
                LegalStatus.EXPIRED,
                LegalStatus.REPEALED,
                LegalStatus.REPLACED,
            }
        ):
            raise ValueError(f"Source document {source.id} is not eligible to retire another document.")
        if (
            superseded.status != DocumentStatus.COMPLETED
            or superseded.review_status != DocumentReviewStatus.APPROVED
            or not superseded.is_current
        ):
            raise ValueError(f"Target document {superseded.id} is not eligible to be retired.")
        if superseded is not None:
            previous_vector_metadata = document_vector_metadata_snapshot(superseded)
            superseded.status = DocumentStatus.BLOCKED
            superseded.is_current = False
            if relation.relation_type == DocumentRelationType.REPEALS:
                superseded.legal_status = LegalStatus.REPEALED
            elif superseded.category == "legal_document":
                superseded.legal_status = LegalStatus.REPLACED

    if commit:
        db.commit()
        db.refresh(relation)
        if superseded is not None:
            db.refresh(superseded)
    else:
        db.flush()
    return relation, superseded, previous_vector_metadata
