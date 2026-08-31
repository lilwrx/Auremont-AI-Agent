from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.core.enums import (
    ConflictStatus,
    DocumentCategory,
    DocumentRelationType,
    DocumentReviewStatus,
    DocumentStatus,
    LegalStatus,
)
from backend.models.conflict_flag import ConflictFlag
from backend.models.document import Document
from backend.models.document_relation import DocumentRelation
from backend.schemas.document import (
    DocumentClassificationUpdate,
    DocumentCreate,
)
from backend.services.document_category_service import document_categories
from backend.services.document_classification_service import (
    DOCUMENT_CLASSIFICATION_VERSION,
    DocumentClassification,
)
from backend.utils.time import utcnow


def create_document(
    db: Session,
    doc_schema: DocumentCreate,
    uploaded_by: int | None = None,
) -> Document:
    document = Document(
        title=doc_schema.title,
        file_path=doc_schema.file_path,
        project_id=doc_schema.project_id,
        visibility=doc_schema.visibility,
        category=doc_schema.category,
        categories=[str(doc_schema.category)],
        section_classifications=[],
        subcategory=doc_schema.subcategory,
        subdivision_names=doc_schema.subdivision_names,
        building_codes=doc_schema.building_codes,
        unit_types=doc_schema.unit_types,
        applicable_area=doc_schema.applicable_area,
        version_label=doc_schema.version_label,
        issued_date=doc_schema.issued_date,
        effective_date=doc_schema.effective_date,
        expiry_date=doc_schema.expiry_date,
        applicable_period=doc_schema.applicable_period,
        legal_document_type=doc_schema.legal_document_type,
        legal_document_number=doc_schema.legal_document_number,
        legal_issuer=doc_schema.legal_issuer,
        legal_domain=doc_schema.legal_domain,
        legal_status=doc_schema.legal_status,
        uploaded_by=uploaded_by,
        status=DocumentStatus.PENDING,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def list_documents(db: Session) -> list[Document]:
    return db.query(Document).order_by(Document.created_at.desc()).all()


def get_document(
    db: Session,
    doc_id: int,
    *,
    for_update: bool = False,
) -> Document | None:
    query = db.query(Document).filter(Document.id == doc_id)
    if for_update:
        query = query.populate_existing().with_for_update()
    return query.first()


def list_completed_siblings(db: Session, project_id: str | None, exclude_id: int) -> list[Document]:
    """Other successfully ingested documents that the new upload may contradict.

    With a project, "sibling" means the same project. Without one it means the other
    documents that also carry no project — a company-wide policy is only comparable to
    another company-wide policy, never to one scoped to a single project.

    Returning `[]` for a project-less document (the previous behaviour) meant those files
    silently left the conflict checks altogether, and the upload form makes the project
    optional. Two identically named price lists uploaded with no project raised nothing at
    all. The caller compensates for the missing project anchor by demanding explicit
    overlapping scope instead — see `_shares_explicit_scope` in ingestion_service.
    """
    query = db.query(Document).filter(
        Document.id != exclude_id,
        Document.status == DocumentStatus.COMPLETED,
    )
    if project_id:
        query = query.filter(or_(Document.project_id == project_id, Document.project_id.is_(None)))

    return query.order_by(Document.created_at.desc()).all()


def delete_document(db: Session, doc_id: int) -> None:
    """Delete a document and everything that references it.

    `conflict_flags` and `document_relations` have no ON DELETE CASCADE, so MySQL
    rejects the document delete outright while either still points at it —
    surfacing as an opaque 500, not the 404/400 an Admin could act on. Both are
    derived data (conflict detection, relation graph), safe to drop alongside
    the document itself.
    """
    document = get_document(db, doc_id)
    if document is None:
        raise ValueError(f"Document with id={doc_id} not found.")

    db.query(ConflictFlag).filter(
        or_(ConflictFlag.document_id_a == doc_id, ConflictFlag.document_id_b == doc_id)
    ).delete(synchronize_session=False)
    db.query(DocumentRelation).filter(
        or_(DocumentRelation.source_document_id == doc_id, DocumentRelation.target_document_id == doc_id)
    ).delete(synchronize_session=False)

    db.delete(document)
    db.commit()


def update_document_status(db: Session, doc_id: int, status: str) -> Document:
    document = get_document(db, doc_id)
    if document is None:
        raise ValueError(f"Document with id={doc_id} not found.")
    document.status = status
    db.commit()
    db.refresh(document)
    return document


def update_document_visibility(
    db: Session,
    doc_id: int,
    visibility: str,
    *,
    commit: bool = True,
) -> Document:
    document = get_document(db, doc_id, for_update=not commit)
    if document is None:
        raise ValueError(f"Document with id={doc_id} not found.")
    document.visibility = visibility
    if commit:
        db.commit()
        db.refresh(document)
    else:
        db.flush()
    return document


def update_document_storage_path(
    db: Session,
    doc_id: int,
    file_path: str,
) -> Document:
    document = get_document(db, doc_id)
    if document is None:
        raise ValueError(f"Document with id={doc_id} not found.")

    document.file_path = file_path
    db.commit()
    db.refresh(document)
    return document


def list_documents_for_metadata_edit(db: Session) -> list[Document]:
    """Ingested documents whose metadata an Admin can correct.

    Includes both LLM suggestions waiting for approval and approved documents whose
    metadata an Admin may need to correct later.
    """

    return (
        db.query(Document)
        .filter(Document.status == DocumentStatus.COMPLETED)
        .order_by(Document.created_at.desc())
        .all()
    )


def update_document_classification(
    db: Session,
    document_id: int,
    payload: DocumentClassificationUpdate,
    reviewed_by: int,
    *,
    commit: bool = True,
) -> Document:
    """Record the Admin's confirmed or corrected classification metadata."""

    document = get_document(db, document_id, for_update=True)
    if document is None:
        raise ValueError(f"Document with id={document_id} not found.")
    if document.status != DocumentStatus.COMPLETED:
        raise ValueError(f"Document {document_id} is not ready for classification review (status={document.status}).")

    updates = payload.model_dump(exclude_unset=True)
    if payload.category != document.category:
        raise ValueError("Changing document category requires quarantine, conflict rescan and controlled re-indexing.")

    if "categories" in updates and [str(value) for value in payload.categories] != document_categories(document):
        raise ValueError("Changing document categories requires quarantine and controlled re-indexing.")
    if "section_classifications" in updates and updates["section_classifications"] != (
        document.section_classifications or []
    ):
        raise ValueError("Changing section categories requires quarantine and controlled re-indexing.")

    scope_fields = ("subdivision_names", "building_codes", "unit_types")
    changed_scope_fields = [
        field_name
        for field_name in scope_fields
        if field_name in updates
        and _normalised_string_set(updates[field_name]) != _normalised_string_set(getattr(document, field_name))
    ]
    if changed_scope_fields:
        raise ValueError(
            "Changing conflict-scope metadata requires a controlled conflict rescan: "
            f"{', '.join(changed_scope_fields)}."
        )

    for field_name, value in updates.items():
        setattr(document, field_name, value)

    if document.legal_status in {
        LegalStatus.NOT_YET_EFFECTIVE,
        LegalStatus.EXPIRED,
        LegalStatus.REPEALED,
        LegalStatus.REPLACED,
    }:
        document.is_current = False

    document.review_status = DocumentReviewStatus.APPROVED
    document.reviewed_by = reviewed_by
    document.reviewed_at = utcnow()

    if commit:
        db.commit()
        db.refresh(document)
    else:
        db.flush()
    return document


def _normalised_string_set(values: list[str] | None) -> frozenset[str]:
    return frozenset(" ".join(value.split()).casefold() for value in (values or []) if value.strip())


def is_document_eligible_after_classification_approval(db: Session, document: Document) -> bool:
    """Whether classification approval is the document's only remaining quarantine."""

    if not any(category != DocumentCategory.OTHER for category in document_categories(document)):
        return False

    if document.legal_status in {
        LegalStatus.NOT_YET_EFFECTIVE,
        LegalStatus.EXPIRED,
        LegalStatus.REPEALED,
        LegalStatus.REPLACED,
    }:
        return False

    has_open_conflict = (
        db.query(ConflictFlag.id)
        .filter(
            ConflictFlag.status == ConflictStatus.OPEN,
            or_(
                ConflictFlag.document_id_a == document.id,
                ConflictFlag.document_id_b == document.id,
            ),
        )
        .first()
        is not None
    )
    if has_open_conflict:
        return False

    has_retirement_relation = (
        db.query(DocumentRelation.id)
        .filter(
            DocumentRelation.target_document_id == document.id,
            DocumentRelation.review_status == DocumentReviewStatus.APPROVED,
            DocumentRelation.relation_type.in_(
                [
                    DocumentRelationType.REPLACES,
                    DocumentRelationType.SUPERSEDES,
                    DocumentRelationType.REPEALS,
                ]
            ),
        )
        .first()
        is not None
    )
    return not has_retirement_relation


def update_document_classification_suggestion(
    db: Session,
    document_id: int,
    classification: DocumentClassification,
    *,
    auto_approve: bool = False,
) -> Document:
    """Store the metadata returned by the document-classification LLM."""

    document = get_document(db, document_id)
    if document is None:
        raise ValueError(f"Document with id={document_id} not found.")

    document.category = classification.category
    document.categories = [str(category) for category in classification.categories]
    document.section_classifications = [
        section.model_dump(mode="json") for section in classification.section_classifications
    ]
    document.subcategory = classification.subcategory
    document.project_id = classification.project_id
    document.subdivision_names = classification.subdivision_names
    document.building_codes = classification.building_codes
    document.unit_types = [str(unit) for unit in classification.unit_types] if classification.unit_types else None
    document.applicable_area = classification.applicable_area

    document.document_summary = classification.document_summary
    document.version_label = classification.version_label
    document.issued_date = classification.issued_date
    document.effective_date = classification.effective_date
    document.expiry_date = classification.expiry_date
    document.applicable_period = classification.applicable_period

    document.legal_document_type = classification.legal_document_type
    document.legal_document_number = classification.legal_document_number
    document.legal_issuer = classification.legal_issuer
    document.legal_domain = classification.legal_domain
    document.legal_status = classification.legal_status
    document.conflict_facts = [fact.model_dump(mode="json") for fact in classification.conflict_facts]

    document.classification_confidence = classification.confidence
    document.classification_reason = classification.reason
    document.classification_requires_admin_review = classification.requires_admin_review
    document.classification_version = DOCUMENT_CLASSIFICATION_VERSION
    document.classified_at = utcnow()

    if auto_approve and not classification.requires_admin_review:
        document.review_status = DocumentReviewStatus.APPROVED
        document.reviewed_by = None
        document.reviewed_at = utcnow()
    else:
        document.review_status = DocumentReviewStatus.PENDING
        document.reviewed_by = None
        document.reviewed_at = None

    db.commit()
    db.refresh(document)
    return document
