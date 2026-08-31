import hashlib
import inspect
import json
import logging
import re
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from io import BytesIO
from pathlib import PurePath
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.enums import (
    ConflictStatus,
    DocumentBlockReason,
    DocumentCategory,
    DocumentReviewStatus,
    DocumentStatus,
    LegalStatus,
)
from backend.core.gemini_client import embed_documents, is_gemini_quota_error
from backend.core.minio_client import ensure_bucket, get_minio_client
from backend.core.sparse_embedding import SparseEmbeddingError, embed_documents_sparse
from backend.models.document import Document
from backend.models.project import Project
from backend.repositories.conflict_flag import create_conflict
from backend.repositories.document import (
    get_document,
    is_document_eligible_after_classification_approval,
    list_completed_siblings,
    update_document_classification_suggestion,
    update_document_status,
    update_document_storage_path,
)
from backend.services.chunking_service import chunk_sections, chunk_sections_by_classification
from backend.services.document_category_service import (
    document_categories,
    document_has_category,
    documents_share_category,
)
from backend.services.document_classification_service import (
    DocumentClassification,
    DocumentClassificationError,
    classify_document,
)
from backend.services.document_conflict_service import (
    DocumentConflictAssessmentError,
    SemanticConflictAssessment,
    assess_semantic_conflict,
)
from backend.services.document_security_service import SecurityFinding, scan_document_sections
from backend.services.parser_service import ParsedSection, parse_document
from backend.services.project_metadata_service import (
    classification_project_catalog,
    resolve_classified_project,
)
from backend.services.vector_store_service import (
    delete_document_vectors,
    index_document_chunks,
    sync_document_vector_metadata,
    update_document_vector_metadata,
)
from backend.utils.text import strip_diacritics
from backend.utils.time import utcnow
from backend.utils.vnd import DOCUMENT_UNIT_ALTERNATION, Profile, parse_vnd

logger = logging.getLogger(__name__)


class PromptInjectionError(ValueError):
    """The document contains instructions attempting to manipulate the AI."""

    def __init__(self, findings: tuple[SecurityFinding, ...]):
        super().__init__("Potential prompt-injection content detected.")
        self.findings = findings


class DocumentIngestionError(RuntimeError):
    """Failure while parsing, storing, embedding or indexing a document."""


AI_SERVICE_QUOTA_PUBLIC_MESSAGE = (
    "Dịch vụ AI tạm thời đã đạt giới hạn sử dụng. Tài liệu đang được cách ly khỏi "
    "kết quả trả lời. Vui lòng thử lại sau; nếu lỗi tiếp diễn, hãy kiểm tra hạn mức dịch vụ AI."
)


class DocumentAIQuotaExceededError(DocumentIngestionError):
    """A safe, retryable document failure caused by upstream AI quota exhaustion."""

    def __init__(self) -> None:
        super().__init__(AI_SERVICE_QUOTA_PUBLIC_MESSAGE)


@dataclass(frozen=True)
class ConflictScanOutcome:
    """The two materially different reasons a new document must stay quarantined."""

    conflict_ids: tuple[int, ...] = ()
    duplicate_document_ids: tuple[int, ...] = ()


@dataclass(frozen=True)
class PreparedSemanticConflict:
    """A source-and-metadata-bound verdict computed before the DB scope lock."""

    sibling_id: int
    current_analysis_hash: str
    sibling_analysis_hash: str
    assessment: SemanticConflictAssessment | None


class SemanticConflictPreparationStaleError(DocumentIngestionError):
    """The locked comparison set differs from the one assessed outside the lock."""


SEMANTIC_CONFLICT_ANALYSIS_VERSION = "hybrid-semantic-v2-grounded"


@dataclass(frozen=True)
class _VectorMetadata:
    """The retrieval-visible state to publish to Qdrant once MySQL is authoritative.

    Captured before `db.commit()` because committing expires the ORM attributes, and a
    dataclass rather than a dict so each field still type-checks against the parameter it
    is passed to.
    """

    review_status: str
    legal_status: str
    category: str
    categories: list[str]
    visibility: str
    is_current: bool


_OPERATOR_TRANSLATIONS: dict[str, str | int | None] = {"≤": "<=", "≥": ">=", "≠": "!="}


def sanitize_and_scan(raw_text: str) -> str:
    """Compatibility wrapper for legacy raw-text ingestion."""
    scan = scan_document_sections([ParsedSection(text=raw_text, page=None)])
    if not scan.sections:
        raise DocumentIngestionError("Document contains no text.")
    if scan.should_block():
        raise PromptInjectionError(scan.findings)
    return scan.text


def ingest_uploaded_document(
    db: Session,
    *,
    document: Document,
    filename: str,
    file_bytes: bytes,
    content_type: str | None,
) -> Document:
    """The complete flow for an uploaded PDF/DOCX file.

    The Document row must exist in the DB first, because document.id is what makes the
    MinIO object key and the Qdrant point IDs stable.
    """
    vector_write_attempted = False
    try:
        update_document_status(db, document.id, DocumentStatus.PROCESSING)

        security_scan = scan_document_sections(parse_document(filename, file_bytes))
        sections = list(security_scan.sections)
        if not sections:
            raise DocumentIngestionError("Document contains no text.")
        if security_scan.should_block():
            raise PromptInjectionError(security_scan.findings)
        raw_text = security_scan.text

        classification_units = chunk_sections(sections, document_category=None)
        content_units = [
            {
                "section_index": unit.index,
                "page": unit.page,
                "content_type": unit.content_type,
                "content": unit.text,
            }
            for unit in classification_units
        ]

        project_catalog = classification_project_catalog(db)
        classification = _classify_document_with_catalog(
            filename,
            raw_text,
            project_catalog,
            content_units=content_units,
        )
        project_resolution = resolve_classified_project(
            selected_project_id=document.project_id,
            suggested_project_id=classification.project_id,
            subdivision_names=classification.subdivision_names,
            catalog=project_catalog,
        )
        classification = classification.model_copy(
            update={
                "project_id": project_resolution.project_id,
                "requires_admin_review": (
                    classification.requires_admin_review or project_resolution.requires_admin_review
                ),
                "reason": (
                    f"{classification.reason} {project_resolution.note}".strip()
                    if project_resolution.note
                    else classification.reason
                ),
            }
        )
        auto_approve = (
            not settings.classification_require_admin_approval_before_indexing
            and classification.category != DocumentCategory.OTHER
            and not classification.requires_admin_review
            and classification.confidence >= settings.classification_auto_approve_threshold
        )
        document = update_document_classification_suggestion(
            db,
            document_id=document.id,
            classification=classification,
            auto_approve=auto_approve,
        )
        document.block_reason = None
        document.security_findings = [finding.as_dict() for finding in security_scan.findings]

        if not auto_approve:
            logger.info(
                "Document classification is waiting for Admin review.",
                extra={
                    "event": "document.classification.review_required",
                    "document_id": document.id,
                    "confidence": classification.confidence,
                    "threshold": settings.classification_auto_approve_threshold,
                    "model_requested_review": classification.requires_admin_review,
                },
            )

        object_key = _store_original_file(
            document_id=document.id,
            filename=filename,
            file_bytes=file_bytes,
            content_type=content_type,
        )
        update_document_storage_path(db, document.id, object_key)

        if not auto_approve:
            document.status = DocumentStatus.COMPLETED
            document.is_current = False
            db.commit()
            db.refresh(document)
            return document

        chunks = chunk_sections_by_classification(
            sections,
            primary_category=document.category,
            section_classifications=document.section_classifications,
        )
        if not chunks:
            raise DocumentIngestionError("No chunks were produced.")

        vector_write_attempted = True
        _embed_and_index(document, chunks, is_current=False)

        semantic_assessments = prepare_semantic_conflict_assessments(db, document, raw_text=raw_text)

        with _conflict_scope_lock(db, document):
            scan = _scan_conflicts_with_prepared(
                db,
                document,
                raw_text=raw_text,
                semantic_assessments=semantic_assessments,
                commit=False,
            )
            has_duplicate = bool(scan.duplicate_document_ids)
            document.is_current = (
                not scan.conflict_ids
                and not has_duplicate
                and document.review_status == DocumentReviewStatus.APPROVED
                and document.legal_status
                not in {
                    LegalStatus.NOT_YET_EFFECTIVE,
                    LegalStatus.EXPIRED,
                    LegalStatus.REPEALED,
                    LegalStatus.REPLACED,
                }
            )

            if has_duplicate:
                document.review_status = DocumentReviewStatus.REJECTED
                document.reviewed_by = None
                document.reviewed_at = utcnow()
                duplicate_ids = ", ".join(str(document_id) for document_id in scan.duplicate_document_ids)
                document.classification_reason = (
                    f"{document.classification_reason or ''} Exact duplicate of document(s): {duplicate_ids}."
                ).strip()

            document.block_reason = DocumentBlockReason.DUPLICATE_CONTENT if has_duplicate else None

            document.status = DocumentStatus.BLOCKED if has_duplicate else DocumentStatus.COMPLETED
            document_id = document.id
            final_vector_metadata = _VectorMetadata(
                review_status=document.review_status,
                legal_status=document.legal_status,
                category=document.category,
                categories=document_categories(document),
                visibility=document.visibility,
                is_current=document.is_current,
            )
            db.commit()

            if final_vector_metadata.is_current or has_duplicate:
                try:
                    update_document_vector_metadata(
                        document_id,
                        review_status=final_vector_metadata.review_status,
                        legal_status=final_vector_metadata.legal_status,
                        category=final_vector_metadata.category,
                        categories=final_vector_metadata.categories,
                        visibility=final_vector_metadata.visibility,
                        is_current=final_vector_metadata.is_current,
                    )
                except Exception:
                    logger.exception(
                        "Final vector metadata sync is pending for document %s.",
                        document_id,
                        extra={
                            "event": "document.vector_metadata.sync_pending",
                            "document_id": document_id,
                        },
                    )

        return document

    except PromptInjectionError as exc:
        db.rollback()
        document.is_current = False
        document.status = DocumentStatus.BLOCKED
        document.block_reason = DocumentBlockReason.PROMPT_INJECTION
        document.security_findings = [finding.as_dict() for finding in exc.findings]
        db.commit()
        raise

    except Exception as exc:
        db.rollback()
        document.is_current = False
        db.commit()
        failed = update_document_status(db, document.id, DocumentStatus.FAILED)

        if vector_write_attempted:
            try:
                sync_document_vector_metadata(failed, is_current=False)
            except Exception:  # pragma: no cover - best-effort safety cleanup
                logger.exception(
                    "Could not quarantine vectors for failed document %s.",
                    failed.id,
                    extra={"event": "document.vector_quarantine.failed", "document_id": failed.id},
                )

        if isinstance(exc, DocumentAIQuotaExceededError):
            raise

        if is_gemini_quota_error(exc):
            raise DocumentAIQuotaExceededError() from exc

        if isinstance(exc, DocumentIngestionError):
            raise

        if isinstance(exc, DocumentClassificationError):
            raise DocumentIngestionError(f"Could not classify document {document.id} with the LLM.") from exc

        raise DocumentIngestionError(f"Could not ingest document {document.id}.") from exc


def _classify_document_with_catalog(
    filename: str,
    raw_text: str,
    project_catalog: Sequence[Mapping[str, object]],
    *,
    content_units: Sequence[Mapping[str, object]] | None = None,
) -> DocumentClassification:
    """Pass live project choices in production while tolerating narrow test doubles."""

    signature = inspect.signature(classify_document)
    accepts_catalog = "project_catalog" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    accepts_content_units = "content_units" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    kwargs: dict[str, Any] = {}
    if accepts_catalog:
        kwargs["project_catalog"] = project_catalog
    if accepts_content_units:
        kwargs["content_units"] = content_units
    if kwargs:
        return classify_document(filename, raw_text, **kwargs)
    return classify_document(filename, raw_text)


def _embed_and_index(document: Document, chunks: list, *, is_current: bool | None = None) -> None:
    """Embed chunks on both channels and write them to Qdrant.

    Shared by first ingestion and re-indexing so the two can never drift into producing
    differently-shaped points. First ingestion passes `is_current=False` to keep the new
    vectors quarantined until the conflict scan clears them.
    """
    vectors: list[list[float]] = []
    batch_size = 32

    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        vectors.extend(
            embed_documents(
                [chunk.text for chunk in batch],
                title=document.title,
            )
        )

    try:
        sparse_vectors = embed_documents_sparse([chunk.text for chunk in chunks])
    except SparseEmbeddingError as exc:
        raise DocumentIngestionError("Could not compute BM25 sparse vectors.") from exc

    index_document_chunks(
        document_id=document.id,
        title=document.title,
        project_id=document.project_id,
        visibility=document.visibility,
        chunks=chunks,
        vectors=vectors,
        sparse_vectors=sparse_vectors,
        category=document.category,
        categories=document_categories(document),
        review_status=document.review_status,
        legal_status=document.legal_status,
        is_current=document.is_current if is_current is None else is_current,
    )


def reindex_document(db: Session, *, document_id: int) -> Document:
    """Re-embed and re-index a document that is already stored, from its original file.

    Exists for schema and model migrations: enabling hybrid retrieval changed the shape
    of a Qdrant point, and every document ingested before that has to be rewritten to
    carry a sparse vector.

    Deliberately skips the prompt-injection scan, classification and conflict flagging —
    all three ran at upload and none depends on the embedding. Old vectors are removed
    first so a document whose chunk count shrank leaves nothing orphaned behind.
    """
    document = get_document(db, document_id)
    if document is None:
        raise DocumentIngestionError(f"Document {document_id} does not exist.")

    if not document.file_path:
        raise DocumentIngestionError(f"Document {document_id} has no stored original file to re-index.")

    try:
        file_bytes = _read_original_file(document.file_path)
        sections = parse_document(document.title, file_bytes)

        chunks = chunk_sections_by_classification(
            sections,
            primary_category=document.category,
            section_classifications=document.section_classifications,
        )
        if not chunks:
            raise DocumentIngestionError("No chunks were produced.")

        delete_document_vectors(document.id)
        _embed_and_index(document, chunks)
    except DocumentAIQuotaExceededError:
        raise
    except DocumentIngestionError:
        raise
    except Exception as exc:
        if is_gemini_quota_error(exc):
            raise DocumentAIQuotaExceededError() from exc
        raise DocumentIngestionError(f"Could not re-index document {document_id}.") from exc

    logger.info(
        "Re-indexed document %s.",
        document.id,
        extra={"event": "document.reindex.success", "document_id": document.id, "chunk_count": len(chunks)},
    )
    return document


def reclassify_document(
    db: Session,
    *,
    document_id: int,
    category: str,
    reviewed_by: int,
    metadata_updates: dict[str, object] | None = None,
) -> Document:
    """Safely correct classification and conflict-scope metadata.

    A plain UPDATE can't do this: category drives how `chunk_sections` splits the document,
    how `scan_conflicts_for` compares it, and what retrieval filters on — a bare label
    change would leave old chunks answering under the new category. Project changes also
    need a re-index since `project_id` lives in every Qdrant payload.

    Fail-closed throughout: the document stops being retrievable before anything changes,
    and only becomes retrievable again once new chunks and a fresh conflict scan both
    succeed.
    """
    document = get_document(db, document_id, for_update=True)
    if document is None:
        raise DocumentIngestionError(f"Document {document_id} does not exist.")
    if document.status != DocumentStatus.COMPLETED:
        raise DocumentIngestionError(
            f"Document {document_id} is not ready to be reclassified (status={document.status})."
        )
    if not document.file_path:
        raise DocumentIngestionError(f"Document {document_id} has no stored original file to re-index.")

    was_pending_review = document.review_status == DocumentReviewStatus.PENDING
    previous_category = document.category
    previous_project_id = document.project_id
    updates = dict(metadata_updates or {})
    allowed_fields = {
        "project_id",
        "subcategory",
        "subdivision_names",
        "building_codes",
        "unit_types",
        "applicable_area",
        "document_summary",
        "version_label",
        "issued_date",
        "effective_date",
        "expiry_date",
        "applicable_period",
        "legal_document_type",
        "legal_document_number",
        "legal_issuer",
        "legal_domain",
        "legal_status",
        "categories",
        "section_classifications",
    }
    unexpected_fields = set(updates) - allowed_fields
    if unexpected_fields:
        raise DocumentIngestionError(
            "Unsupported controlled metadata correction fields: " + ", ".join(sorted(unexpected_fields)) + "."
        )

    target_project_id = updates.get("project_id", document.project_id)
    if target_project_id is not None and not isinstance(target_project_id, str):
        raise DocumentIngestionError("project_id must be a project catalogue id or null.")
    if target_project_id and db.get(Project, target_project_id) is None:
        raise DocumentIngestionError(f"project_id '{target_project_id}' does not exist in the project catalogue.")

    raw_section_classifications = updates.get(
        "section_classifications",
        document.section_classifications or [],
    )
    target_section_classifications: list[dict[str, Any]] = (
        [item for item in raw_section_classifications if isinstance(item, dict)]
        if isinstance(raw_section_classifications, list)
        else []
    )
    section_categories = [str(item.get("category")) for item in target_section_classifications if item.get("category")]
    category_changed = category != document.category
    raw_categories = updates.get("categories")
    if "categories" in updates:
        target_categories = [str(value) for value in raw_categories] if isinstance(raw_categories, list) else []
    elif category_changed:
        target_categories = [str(category), *section_categories]
    else:
        target_categories = document_categories(document)
    target_categories = list(dict.fromkeys([str(category), *target_categories, *section_categories]))
    if "categories" in updates or category_changed or "section_classifications" in updates:
        updates["categories"] = target_categories
    categories_changed = target_categories != document_categories(document)
    section_categories_changed = target_section_classifications != (document.section_classifications or [])
    project_changed = target_project_id != document.project_id
    changed_fields = {field_name for field_name, value in updates.items() if value != getattr(document, field_name)}
    if not category_changed and not changed_fields and not was_pending_review:
        raise DocumentIngestionError(
            f"Document {document_id} is already categorised as {category} and has no metadata corrections."
        )
    if was_pending_review and category == DocumentCategory.OTHER:
        raise DocumentIngestionError(
            "A document classified as 'other' cannot be approved for AI retrieval. "
            "Choose a supported business category or remove the document."
        )

    requires_reindex = (
        was_pending_review or category_changed or categories_changed or section_categories_changed or project_changed
    )
    previous_update_values = {field_name: getattr(document, field_name) for field_name in updates}

    if not was_pending_review:
        # Quarantine the indexed version under its pre-update labels.
        update_document_vector_metadata(
            document.id,
            review_status=document.review_status,
            legal_status=document.legal_status,
            category=previous_category,
            categories=document_categories(document),
            visibility=document.visibility,
            is_current=False,
        )
    document.is_current = False
    db.commit()

    chunks: list = []
    try:
        if requires_reindex:
            file_bytes = _read_original_file(document.file_path)
            sections = parse_document(document.title, file_bytes)
            chunks = chunk_sections_by_classification(
                sections,
                primary_category=category,
                section_classifications=target_section_classifications,
            )
            if not chunks:
                raise DocumentIngestionError("No chunks were produced for the corrected classification.")
            section_texts = [
                section.text if isinstance(section, ParsedSection) else str(section) for section in sections
            ]
            comparison_text = sanitize_and_scan("\n\n".join(value for value in section_texts if value.strip()))
        elif settings.semantic_conflict_detection_enabled:
            comparison_text = _read_original_text(document)
        else:
            comparison_text = None

        comparison_document = _comparison_document_with_updates(
            document,
            category=category,
            updates=updates,
        )
        semantic_assessments = prepare_semantic_conflict_assessments(
            db,
            comparison_document,
            raw_text=comparison_text,
        )

        with _conflict_scope_lock(db, document, scope=(target_project_id, str(category))):
            refreshed = get_document(db, document_id, for_update=True)
            if refreshed is None:  # pragma: no cover - deletion also requires this row lock
                raise DocumentIngestionError(f"Document {document_id} no longer exists.")
            if refreshed.status != DocumentStatus.COMPLETED:
                raise DocumentIngestionError(
                    f"Document {document_id} is no longer ready to be corrected (status={refreshed.status})."
                )
            if was_pending_review and refreshed.review_status != DocumentReviewStatus.PENDING:
                raise DocumentIngestionError(
                    f"Document {document_id} was reviewed while this approval was running; reload it and retry."
                )
            if (
                refreshed.category != previous_category
                or refreshed.project_id != previous_project_id
                or any(
                    getattr(refreshed, field_name) != previous_value
                    for field_name, previous_value in previous_update_values.items()
                )
            ):
                raise DocumentIngestionError(
                    f"Document {document_id} changed while the correction was running; reload it and retry."
                )

            document = refreshed
            document.category = category
            for field_name, value in updates.items():
                setattr(document, field_name, value)
            document.review_status = DocumentReviewStatus.APPROVED
            document.reviewed_by = reviewed_by
            document.reviewed_at = utcnow()
            db.flush()

            if requires_reindex:
                delete_document_vectors(document.id)
                _embed_and_index(document, chunks, is_current=False)

            scan = _scan_conflicts_with_prepared(
                db,
                document,
                raw_text=comparison_text,
                semantic_assessments=semantic_assessments,
                commit=False,
            )
            has_duplicate = bool(scan.duplicate_document_ids)
            if has_duplicate:
                document.review_status = DocumentReviewStatus.REJECTED
                document.reviewed_by = reviewed_by
                document.reviewed_at = utcnow()
                document.status = DocumentStatus.BLOCKED
                duplicate_ids = ", ".join(str(value) for value in scan.duplicate_document_ids)
                document.classification_reason = (
                    f"{document.classification_reason or ''} Exact duplicate of document(s): {duplicate_ids}."
                ).strip()
                document.is_current = False
            else:
                document.is_current = (
                    not scan.conflict_ids
                    and category != DocumentCategory.OTHER
                    and is_document_eligible_after_classification_approval(db, document)
                )
            db.commit()

            refreshed = get_document(db, document_id, for_update=True)
            if refreshed is None:  # pragma: no cover - deletion also requires this row lock
                raise DocumentIngestionError(f"Document {document_id} no longer exists.")
            document = refreshed
            publication_current = bool(
                document.is_current
                and document.status == DocumentStatus.COMPLETED
                and document.review_status == DocumentReviewStatus.APPROVED
                and document.category != DocumentCategory.OTHER
                and is_document_eligible_after_classification_approval(db, document)
            )
            if document.is_current != publication_current:
                document.is_current = publication_current
                db.flush()
            sync_document_vector_metadata(document, is_current=publication_current)
            db.commit()
    except Exception as exc:
        db.rollback()
        if was_pending_review and requires_reindex:
            try:
                persisted = get_document(db, document_id)
                if persisted is not None:
                    if persisted.is_current:
                        persisted.is_current = False
                        db.commit()
                        db.refresh(persisted)
                    sync_document_vector_metadata(persisted, is_current=False)
            except Exception:  # pragma: no cover - best-effort cross-store reconciliation
                logger.exception(
                    "Could not reassert pending vector quarantine for document %s.",
                    document_id,
                    extra={
                        "event": "document.approval.vector_quarantine.failed",
                        "document_id": document_id,
                    },
                )
        logger.exception(
            "Reclassifying document %s failed; it stays quarantined.",
            document_id,
            extra={
                "event": "document.reclassify.failed",
                "document_id": document_id,
                "from_category": previous_category,
                "to_category": category,
                "from_project_id": previous_project_id,
                "to_project_id": target_project_id,
            },
        )
        if isinstance(exc, DocumentAIQuotaExceededError):
            raise
        if is_gemini_quota_error(exc):
            raise DocumentAIQuotaExceededError() from exc
        if isinstance(exc, DocumentIngestionError):
            raise
        raise DocumentIngestionError(f"Could not reclassify document {document_id}.") from exc

    logger.info(
        "Reclassified document %s.",
        document_id,
        extra={
            "event": "document.reclassify.success",
            "document_id": document_id,
            "from_category": previous_category,
            "to_category": category,
            "from_project_id": previous_project_id,
            "to_project_id": target_project_id,
            "chunk_count": len(chunks),
            "is_current": document.is_current,
        },
    )
    db.refresh(document)
    return document


def _read_original_file(object_key: str) -> bytes:
    """Fetch a stored original back out of MinIO."""
    response = None
    try:
        response = get_minio_client().get_object(
            bucket_name=settings.minio_bucket_documents,
            object_name=object_key,
        )
        return response.read()
    except Exception as exc:
        raise DocumentIngestionError("Could not read the original file from MinIO.") from exc
    finally:
        if response is not None:
            response.close()
            response.release_conn()


def prepare_semantic_conflict_assessments(
    db: Session,
    document: Document,
    *,
    raw_text: str | None = None,
) -> dict[int, PreparedSemanticConflict]:
    """Run bounded semantic comparisons before the conflict-scope DB lock."""

    if not settings.semantic_conflict_detection_enabled:
        return {}

    current_text = raw_text if raw_text is not None else _read_original_text(document)
    current_content_key = _content_key(current_text)
    if not current_content_key:
        raise DocumentIngestionError(f"Document {document.id} has no comparable parsed content.")
    current_analysis_hash = _semantic_analysis_hash(document, current_content_key)

    prepared: dict[int, PreparedSemanticConflict] = {}
    remaining = settings.semantic_conflict_max_candidates
    for sibling in list_completed_siblings(db, document.project_id, exclude_id=document.id):
        if not _is_semantic_scope_candidate(document, sibling):
            continue

        sibling_text = _read_original_text(sibling)
        sibling_content_key = _content_key(sibling_text)
        if not sibling_content_key:
            raise DocumentIngestionError(
                f"Cannot verify conflicts because completed document {sibling.id} has no parsed source content."
            )
        if current_content_key == sibling_content_key or (
            _meaningful_content_key(current_text) == _meaningful_content_key(sibling_text)
        ):
            continue
        if _has_deterministic_conflict(document, sibling, current_text=current_text, sibling_text=sibling_text):
            continue

        if remaining <= 0:
            message = (
                f"Semantic conflict candidate limit was exceeded for document {document.id}; "
                "the document cannot be published without assessing every relevant sibling."
            )
            if settings.semantic_conflict_fail_closed:
                raise DocumentIngestionError(message)
            logger.warning(
                message,
                extra={
                    "event": "document.conflict.semantic.candidate_limit_exceeded",
                    "document_id": document.id,
                    "candidate_limit": settings.semantic_conflict_max_candidates,
                },
            )
            break

        try:
            assessment = assess_semantic_conflict(
                sibling,
                sibling_text,
                document,
                current_text,
                facts_a=sibling.conflict_facts,
                facts_b=document.conflict_facts,
            )
        except DocumentConflictAssessmentError as exc:
            if settings.semantic_conflict_fail_closed:
                raise DocumentIngestionError(
                    f"Could not complete semantic conflict analysis for document {document.id}."
                ) from exc
            logger.warning(
                "Semantic conflict analysis was skipped after an LLM failure.",
                extra={
                    "event": "document.conflict.semantic.skipped",
                    "document_id": document.id,
                    "sibling_id": sibling.id,
                },
            )
            assessment = None

        prepared[sibling.id] = PreparedSemanticConflict(
            sibling_id=sibling.id,
            current_analysis_hash=current_analysis_hash,
            sibling_analysis_hash=_semantic_analysis_hash(sibling, sibling_content_key),
            assessment=assessment,
        )
        if assessment is not None:
            logger.info(
                "Semantic conflict assessment completed.",
                extra={
                    "event": "document.conflict.semantic.completed",
                    "document_id": document.id,
                    "sibling_id": sibling.id,
                    "decision": assessment.decision,
                    "confidence": assessment.confidence,
                    "analysis_version": SEMANTIC_CONFLICT_ANALYSIS_VERSION,
                },
            )
        remaining -= 1

    return prepared


_COMPARISON_DOCUMENT_FIELDS = (
    "id",
    "title",
    "file_path",
    "project_id",
    "category",
    "categories",
    "section_classifications",
    "subcategory",
    "subdivision_names",
    "building_codes",
    "unit_types",
    "applicable_area",
    "version_label",
    "issued_date",
    "effective_date",
    "expiry_date",
    "applicable_period",
    "legal_document_number",
    "legal_status",
    "conflict_facts",
)


def _semantic_analysis_hash(document: Document, content_key: str) -> str:
    """Fingerprint every input that can change a semantic verdict.

    Conflict analysis happens before the project-wide advisory lock so the LLM never
    holds a database lock.  The locked scan must therefore reject not just changed file
    bytes, but also changed scope, effective dates and extracted conflict facts.
    """

    payload = {
        "content": content_key,
        "metadata": {
            field: getattr(document, field, None)
            for field in _COMPARISON_DOCUMENT_FIELDS
            if field not in {"id", "file_path"}
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _comparison_document_with_updates(
    document: Document,
    *,
    category: str,
    updates: dict[str, object],
) -> Document:
    """Build a detached metadata view for pre-lock semantic assessment."""

    values = {field: getattr(document, field) for field in _COMPARISON_DOCUMENT_FIELDS}
    values["category"] = category
    values.update(updates)
    return Document(**values)


def flag_conflicts_for(
    db: Session,
    document: Document,
    *,
    raw_text: str | None = None,
    commit: bool = True,
) -> list[int]:
    """Compatibility wrapper returning only flags created/found by the scan."""
    semantic_assessments = prepare_semantic_conflict_assessments(db, document, raw_text=raw_text)
    return list(
        _scan_conflicts_with_prepared(
            db,
            document,
            raw_text=raw_text,
            semantic_assessments=semantic_assessments,
            commit=commit,
        ).conflict_ids
    )


def _scan_conflicts_with_prepared(
    db: Session,
    document: Document,
    *,
    raw_text: str | None,
    semantic_assessments: dict[int, PreparedSemanticConflict],
    commit: bool,
) -> ConflictScanOutcome:
    """Pass new semantic input while tolerating intentionally narrow test doubles."""

    signature = inspect.signature(scan_conflicts_for)
    accepts_semantic = "semantic_assessments" in signature.parameters or any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in signature.parameters.values()
    )
    if accepts_semantic:
        return scan_conflicts_for(
            db,
            document,
            raw_text=raw_text,
            semantic_assessments=semantic_assessments,
            commit=commit,
        )
    return scan_conflicts_for(db, document, raw_text=raw_text, commit=commit)


def scan_conflicts_for(
    db: Session,
    document: Document,
    *,
    raw_text: str | None = None,
    semantic_assessments: dict[int, PreparedSemanticConflict] | None = None,
    commit: bool = True,
) -> ConflictScanOutcome:
    """Apply deterministic rules plus precomputed, source-grounded LLM verdicts."""
    current_text = raw_text if raw_text is not None else _read_original_text(document)
    current_content_key = _content_key(current_text)
    if not current_content_key:
        raise DocumentIngestionError(f"Document {document.id} has no comparable parsed content.")
    current_analysis_hash = _semantic_analysis_hash(document, current_content_key)
    rule_candidates: list[
        tuple[
            Document,
            list[tuple[str, set[int], set[int]]],
            list[tuple[str, set[str], set[str]]],
        ]
    ] = []
    semantic_candidates: list[tuple[Document, SemanticConflictAssessment]] = []
    semantic_enabled = settings.semantic_conflict_detection_enabled
    prepared = semantic_assessments or {}
    semantic_candidate_count = 0

    for sibling in list_completed_siblings(db, document.project_id, exclude_id=document.id):
        rule_scope = document.project_id == sibling.project_id and _same_business_scope(document, sibling)
        semantic_scope = semantic_enabled and _is_semantic_scope_candidate(document, sibling)
        if not rule_scope and not semantic_scope:
            continue

        same_title = _title_key(sibling.title) == _title_key(document.title)
        same_identity = same_title or _shares_legal_identity(document, sibling)
        sibling_text = _read_original_text(sibling)
        sibling_content_key = _content_key(sibling_text)

        if not sibling_content_key:
            raise DocumentIngestionError(
                f"Cannot verify conflicts because completed document {sibling.id} has no parsed source content."
            )

        if current_content_key == sibling_content_key:
            return ConflictScanOutcome(duplicate_document_ids=(sibling.id,))
        if _meaningful_content_key(current_text) == _meaningful_content_key(sibling_text):
            return ConflictScanOutcome(duplicate_document_ids=(sibling.id,))

        price_differences: list[tuple[str, set[int], set[int]]] = []
        fact_differences: list[tuple[str, set[str], set[str]]] = []
        has_shared_price_scope = False
        if rule_scope:
            fact_differences = [
                *_business_fact_differences(sibling_text, current_text),
                *_textual_clause_differences(sibling_text, current_text),
            ]
        if (
            rule_scope
            and document_has_category(document, DocumentCategory.PRICE_LIST)
            and document_has_category(sibling, DocumentCategory.PRICE_LIST)
        ):
            old_price_facts = _price_facts(sibling_text)
            new_price_facts = _price_facts(current_text)
            price_differences = _price_differences_from_facts(old_price_facts, new_price_facts)
            has_shared_price_scope = bool((old_price_facts.keys() & new_price_facts.keys()) - {"__DOCUMENT_PRICES__"})

        rule_scope_is_grounded = bool(
            document.project_id
            or same_identity
            or _shares_explicit_scope(document, sibling)
            or _has_content_scope_evidence(has_shared_price_scope, fact_differences)
        )
        if rule_scope and rule_scope_is_grounded and (price_differences or fact_differences):
            rule_candidates.append((sibling, price_differences, fact_differences))
            continue

        if rule_scope and rule_scope_is_grounded and same_identity and not semantic_enabled:
            rule_candidates.append((sibling, price_differences, fact_differences))
            continue

        if not semantic_scope or not (
            document.project_id
            or same_identity
            or _shares_explicit_scope(document, sibling)
            or _shared_conflict_fact_keys(document, sibling)
        ):
            continue

        semantic_candidate_count += 1
        if semantic_candidate_count > settings.semantic_conflict_max_candidates:
            if settings.semantic_conflict_fail_closed:
                raise DocumentIngestionError(
                    f"Semantic conflict candidate limit was exceeded for document {document.id}."
                )
            continue

        prepared_pair = prepared.get(sibling.id)
        sibling_hash = _semantic_analysis_hash(sibling, sibling_content_key)
        if (
            prepared_pair is None
            or prepared_pair.current_analysis_hash != current_analysis_hash
            or prepared_pair.sibling_analysis_hash != sibling_hash
        ):
            raise SemanticConflictPreparationStaleError(
                f"Semantic comparison set changed before document {document.id} could be published."
            )
        assessment = prepared_pair.assessment
        if assessment is None:
            continue
        if assessment.decision == "compatible" and assessment.confidence >= settings.semantic_conflict_min_confidence:
            continue
        semantic_candidates.append((sibling, assessment))

    created: list[int] = []
    for sibling, price_differences, fact_differences in rule_candidates:
        conflict_type = "price" if price_differences else "business_fact" if fact_differences else "document_change"
        conflict = create_conflict(
            db,
            document_id_a=sibling.id,
            document_id_b=document.id,
            description=(
                f"Phát hiện nội dung khác nhau giữa '{sibling.title}' và "
                f"'{document.title}' trong cùng phạm vi áp dụng."
                f"{_format_price_differences(price_differences)}"
                f"{_format_fact_differences(fact_differences)} "
                "Kiểm tra và chọn bản được ưu tiên."
            ),
            detection_method="rule",
            confidence=1.0,
            conflict_type=conflict_type,
            evidence=_rule_evidence_payload(price_differences, fact_differences),
            analysis_version=SEMANTIC_CONFLICT_ANALYSIS_VERSION,
            commit=False,
        )
        if conflict.status == ConflictStatus.OPEN:
            created.append(conflict.id)

    for sibling, assessment in semantic_candidates:
        confirmed = assessment.decision == "conflict" and (
            assessment.confidence >= settings.semantic_conflict_min_confidence
        )
        description = (
            f"AI phát hiện mâu thuẫn ngữ nghĩa giữa '{sibling.title}' và '{document.title}': {assessment.summary}"
            if confirmed
            else (
                f"AI chưa thể loại trừ mâu thuẫn giữa '{sibling.title}' và '{document.title}': "
                f"{assessment.summary} Cần Admin kiểm tra bằng chứng hai phía."
            )
        )
        conflict = create_conflict(
            db,
            document_id_a=sibling.id,
            document_id_b=document.id,
            description=description,
            detection_method="llm",
            confidence=assessment.confidence,
            conflict_type=assessment.conflict_type or "semantic_uncertain",
            evidence=_semantic_evidence_payload(assessment),
            analysis_version=SEMANTIC_CONFLICT_ANALYSIS_VERSION,
            commit=False,
        )
        if conflict.status == ConflictStatus.OPEN:
            created.append(conflict.id)

    if commit:
        db.commit()

    return ConflictScanOutcome(conflict_ids=tuple(created))


@contextmanager
def _conflict_scope_lock(
    db: Session,
    document: Document,
    *,
    scope: tuple[str | None, str] | None = None,
) -> Iterator[None]:
    """Use a MySQL advisory lock to serialize conflict scans for one scope.

    SQLite is used by unit tests and has no cross-connection advisory lock. Production
    MySQL holds this named lock on a dedicated connection, independent of commits made
    by the ingestion session, until the compare-and-activate section has finished.
    """
    bind = db.get_bind()
    if not isinstance(bind, Engine):
        raise DocumentIngestionError("The conflict lock requires a SQLAlchemy engine binding.")
    if bind.dialect.name != "mysql":
        yield
        return

    scope_project_id, scope_category = scope or (document.project_id, str(document.category))
    if settings.semantic_conflict_detection_enabled:
        scope_project_id = "__all_projects__"
        scope_category = "__semantic_all_categories__"
    scope_key = f"{scope_project_id or '__global__'}:{scope_category}"
    digest = hashlib.sha256(scope_key.encode("utf-8")).hexdigest()[:40]
    lock_name = f"salesmate-ingest:{digest}"

    db.rollback()
    db.expire_all()
    db.connection()

    with bind.connect() as lock_connection:
        acquired = lock_connection.execute(
            text("SELECT GET_LOCK(:lock_name, :timeout_seconds)"),
            {"lock_name": lock_name, "timeout_seconds": 30},
        ).scalar()
        if acquired != 1:
            raise DocumentIngestionError("Timed out waiting for the document conflict-scan lock.")
        try:
            yield
        finally:
            try:
                lock_connection.execute(
                    text("SELECT RELEASE_LOCK(:lock_name)"),
                    {"lock_name": lock_name},
                )
            except Exception:  # pragma: no cover - connection cleanup only
                logger.exception(
                    "Could not release ingestion conflict lock %s.",
                    lock_name,
                    extra={"event": "document.conflict_lock.release_failed"},
                )
                lock_connection.invalidate()


def _title_key(title: str | None) -> str:
    """Normalise a title while ignoring file format, version and period suffixes."""
    if not title:
        return ""
    normalised = strip_diacritics(PurePath(title).stem)
    normalised = re.sub(r"[^a-z0-9]+", " ", normalised)
    normalised = re.sub(
        r"\b(?:v|ver|version|phien\s+ban)\s*\d+(?:\s+\d+){0,2}\b",
        " ",
        normalised,
    )
    normalised = re.sub(r"\b(?:thang|dot|ky)\s+\d{1,4}(?:\s+20\d{2})?\b", " ", normalised)
    normalised = re.sub(r"\b(?:quy|q)\s*[1-4](?:\s+20\d{2})?\b", " ", normalised)
    return " ".join(normalised.split())


def _content_key(text: str) -> str:
    """Collapse formatting differences before deciding whether content changed."""
    return " ".join(strip_diacritics(text.replace("\x00", "")).split())


def _meaningful_content_key(text: str) -> str:
    """Ignore layout punctuation while retaining operators that can change meaning."""
    normalised = text.replace("\x00", "").translate(str.maketrans(_OPERATOR_TRANSLATIONS))
    normalised = strip_diacritics(normalised)
    normalised = re.sub(r"[^a-z0-9%<>=+!]+", " ", normalised)
    normalised = re.sub(r"\s*([%<>=+!])\s*", r"\1", normalised)
    return " ".join(normalised.split())


_UNIT_CODE_RE = re.compile(
    r"\b(?:"
    r"(?=[A-Z0-9.-]*[A-Z])(?=[A-Z0-9.-]*\d)[A-Z0-9]+(?:[-.][A-Z0-9]+)+"
    r"|(?:[A-Z]{2,3}\d{1,4}|[A-Z]\d{2,4})"
    r")\b",
    re.IGNORECASE,
)
_NON_UNIT_CODE_RE = re.compile(
    r"^(?:DOT|THANG|NAM|QUY|PN|CSBH|VND|TANG|LOAI|STT|GIA|MA|CAN|KY|LAN)\d+$",
    re.IGNORECASE,
)
_PRICE_RE = re.compile(
    rf"(?<!\w)(\d{{1,3}}(?:[.,]\d{{3}}){{2,}}|\d+(?:[.,]\d+)?)\s*({DOCUMENT_UNIT_ALTERNATION})\b",
    re.IGNORECASE,
)
_COMPOUND_PRICE_RE = re.compile(
    r"(?<!\w)(?P<billions>\d+(?:[.,]\d+)?)\s*(?:tỷ|ty|billion)\s*"
    r"(?P<millions>\d+(?:[.,]\d+)?)\s*(?:triệu|trieu|tr|million)\b",
    re.IGNORECASE,
)
_BARE_GROUPED_VND_RE = re.compile(r"(?<!\w)(\d{1,3}(?:[.,]\d{3})+)(?!\w)")
_VND_TABLE_CONTEXT_RE = re.compile(
    r"(?:gia|don\s+gia).{0,40}\b(?:vnd|dong)\b|\b(?:vnd|dong)\b.{0,40}(?:gia|don\s+gia)",
    re.IGNORECASE,
)
_FACT_VALUE_RE = re.compile(
    r"(?P<date>\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b)"
    r"|(?P<percent>(?<!\w)\d+(?:[.,]\d+)?\s*(?:%|phan\s+tram))"
    r"|(?P<money>(?<!\w)(?:\d{1,3}(?:[.,]\d{3}){2,}|\d+(?:[.,]\d+)?)\s*"
    r"(?:ty|trieu|tr|million|billion|vnd|dong)\b)"
    r"|(?P<measure>(?<!\w)\d+(?:[.,]\d+)?\s*"
    r"(?:ngay|thang|nam|dot|ky|lan|m2|m²|can|suat)\b)",
    re.IGNORECASE,
)
_NORMALIZED_MONEY_RE = re.compile(
    r"(\d{1,3}(?:[.,]\d{3}){2,}|\d+(?:[.,]\d+)?)\s*"
    r"(ty|trieu|tr|million|billion|vnd|dong)",
    re.IGNORECASE,
)


_SCOPE_FIELDS = ("subdivision_names", "building_codes", "unit_types")


def _scope_values(document: Document, field: str) -> set[str]:
    return {key for value in (getattr(document, field) or []) if (key := _metadata_key(str(value)))}


def _metadata_key(value: str | None) -> str:
    if not value:
        return ""
    normalised = strip_diacritics(value)
    return " ".join(re.sub(r"[^a-z0-9+]+", " ", normalised).split())


def _same_business_scope(left: Document, right: Document) -> bool:
    """Compare scope using location before the narrower unit-type hint.

    Subdivision and building are strong location boundaries: populated, disjoint values
    prove that two documents concern different places. A shared building, however, keeps
    the documents comparable even when their extracted unit-type lists differ; that
    difference can itself represent a price list adding or removing a product type.
    Missing metadata remains "unknown", not proof of separation.
    """
    if not documents_share_category(left, right):
        return False

    for field in ("subdivision_names", "building_codes"):
        left_values = _scope_values(left, field)
        right_values = _scope_values(right, field)
        if left_values and right_values and not left_values & right_values:
            return False

    shares_location = any(
        _scope_values(left, field) & _scope_values(right, field) for field in ("subdivision_names", "building_codes")
    )
    if shares_location:
        return True

    left_unit_types = _scope_values(left, "unit_types")
    right_unit_types = _scope_values(right, "unit_types")
    return not (left_unit_types and right_unit_types and not left_unit_types & right_unit_types)


_SEMANTIC_CATEGORY_GROUPS = (
    frozenset(
        {
            DocumentCategory.SALES_POLICY,
            DocumentCategory.PRICE_LIST,
            DocumentCategory.INVENTORY_SNAPSHOT,
            DocumentCategory.PAYMENT_SCHEDULE,
            DocumentCategory.PROMOTION,
            DocumentCategory.CONTRACT_TEMPLATE,
        }
    ),
    frozenset(
        {
            DocumentCategory.SUBDIVISION_INFO,
            DocumentCategory.BUILDING_INFO,
            DocumentCategory.FLOOR_PLAN,
            DocumentCategory.INVENTORY_SNAPSHOT,
        }
    ),
    frozenset(
        {
            DocumentCategory.LEGAL_DOCUMENT,
            DocumentCategory.CONTRACT_TEMPLATE,
            DocumentCategory.INTERNAL_GUIDE,
        }
    ),
)


def _is_semantic_scope_candidate(left: Document, right: Document) -> bool:
    """Select pairs broadly enough for paraphrases, without comparing unrelated files."""

    if left.project_id and right.project_id and left.project_id != right.project_id:
        return False
    for field in ("subdivision_names", "building_codes"):
        left_values = _scope_values(left, field)
        right_values = _scope_values(right, field)
        if left_values and right_values and not left_values & right_values:
            return False

    same_identity = _title_key(left.title) == _title_key(right.title) or _shares_legal_identity(left, right)
    if same_identity or _shares_explicit_scope(left, right) or _shared_conflict_fact_keys(left, right):
        return True
    left_categories = set(document_categories(left))
    right_categories = set(document_categories(right))
    global_and_project = bool(left.project_id) != bool(right.project_id)
    if global_and_project and left_categories & right_categories:
        return True
    if not left.project_id and not right.project_id:
        return bool(left_categories & right_categories) or any(
            left_categories & group and right_categories & group for group in _SEMANTIC_CATEGORY_GROUPS
        )
    if left_categories & right_categories:
        return True
    return any(left_categories & group and right_categories & group for group in _SEMANTIC_CATEGORY_GROUPS)


def _shared_conflict_fact_keys(left: Document, right: Document) -> bool:
    def keys(document: Document) -> set[str]:
        result: set[str] = set()
        for fact in document.conflict_facts or []:
            if not isinstance(fact, dict):
                continue
            key = _metadata_key(str(fact.get("fact_key") or ""))
            if key:
                result.add(key)
        return result

    left_keys = keys(left)
    right_keys = keys(right)
    return bool(left_keys and right_keys and left_keys & right_keys)


def _has_deterministic_conflict(
    current: Document,
    sibling: Document,
    *,
    current_text: str,
    sibling_text: str,
) -> bool:
    """Mirror decisive local signals so preparation does not spend an LLM call on them."""

    if current.project_id != sibling.project_id:
        return False
    if not _same_business_scope(current, sibling):
        return False
    fact_differences = [
        *_business_fact_differences(sibling_text, current_text),
        *_textual_clause_differences(sibling_text, current_text),
    ]
    has_shared_price_scope = False
    price_differences: list[tuple[str, set[int], set[int]]] = []
    if document_has_category(current, DocumentCategory.PRICE_LIST) and document_has_category(
        sibling, DocumentCategory.PRICE_LIST
    ):
        old_price_facts = _price_facts(sibling_text)
        new_price_facts = _price_facts(current_text)
        price_differences = _price_differences_from_facts(old_price_facts, new_price_facts)
        has_shared_price_scope = bool((old_price_facts.keys() & new_price_facts.keys()) - {"__DOCUMENT_PRICES__"})
    if not price_differences and not fact_differences:
        return False
    if current.project_id:
        return True
    same_identity = _title_key(current.title) == _title_key(sibling.title) or _shares_legal_identity(current, sibling)
    return bool(
        same_identity
        or _shares_explicit_scope(current, sibling)
        or _has_content_scope_evidence(has_shared_price_scope, fact_differences)
    )


def _shares_explicit_scope(left: Document, right: Document) -> bool:
    """True when both documents name at least one identical subdivision, building or unit type.

    The strict counterpart to `_same_business_scope`, for documents carrying no project:
    there, "might overlap" would match everything, so real evidence is required.
    """
    return any(_scope_values(left, field) & _scope_values(right, field) for field in _SCOPE_FIELDS)


def _shares_legal_identity(left: Document, right: Document) -> bool:
    """A legal document number is a stronger identity anchor than its upload title."""
    if not document_has_category(left, DocumentCategory.LEGAL_DOCUMENT) or not document_has_category(
        right, DocumentCategory.LEGAL_DOCUMENT
    ):
        return False
    left_number = _metadata_key(left.legal_document_number)
    right_number = _metadata_key(right.legal_document_number)
    return bool(left_number and right_number and left_number == right_number)


def _business_fact_differences(
    old_text: str,
    new_text: str,
) -> list[tuple[str, set[str], set[str]]]:
    """Find shared policy clauses/table rows whose measurable values changed.

    The anchor is the normalised line with the measurable value replaced by a token.
    This deliberately requires the surrounding wording to agree; two unrelated numbers
    in the same project are not enough to raise a conflict.
    """
    old_facts = _business_facts(old_text)
    new_facts = _business_facts(new_text)
    return [
        (anchor, old_facts[anchor], new_facts[anchor])
        for anchor in sorted(old_facts.keys() & new_facts.keys())
        if old_facts[anchor] != new_facts[anchor]
    ]


_CLAUSE_POLARITY_RE = re.compile(r"\b(?:khong|chua|da)\b", re.IGNORECASE)
_NEGATIVE_CLAUSE_RE = re.compile(r"\b(?:khong|chua)\b", re.IGNORECASE)
_BUSINESS_CLAUSE_RE = re.compile(
    r"\b(?:khach|gia|vat|chiet\s+khau|thanh\s+toan|dat\s+coc|qua\s+tang|uu\s+dai|"
    r"ap\s+dung|ho\s+tro|lai\s+suat|ban\s+giao|so\s+huu|duoc|phai|bao\s+gom|gom)\b",
    re.IGNORECASE,
)


def _textual_clause_differences(
    old_text: str,
    new_text: str,
) -> list[tuple[str, set[str], set[str]]]:
    """Detect affirmative/negative changes in otherwise identical business clauses."""
    old_facts = _textual_clause_facts(old_text)
    new_facts = _textual_clause_facts(new_text)
    return [
        (f"text:{anchor}", old_facts[anchor], new_facts[anchor])
        for anchor in sorted(old_facts.keys() & new_facts.keys())
        if old_facts[anchor] != new_facts[anchor]
    ]


def _textual_clause_facts(text: str) -> dict[str, set[str]]:
    facts: dict[str, set[str]] = {}
    for raw_line in text.splitlines():
        line = " ".join(strip_diacritics(raw_line).split())
        if not _BUSINESS_CLAUSE_RE.search(line):
            continue
        polarity = "negative" if _NEGATIVE_CLAUSE_RE.search(line) else "affirmative"
        anchor = _CLAUSE_POLARITY_RE.sub(" ", line)
        anchor = " ".join(re.sub(r"[^a-z0-9]+", " ", anchor).split())
        if len(anchor.split()) < 3:
            continue
        facts.setdefault(anchor, set()).add(polarity)
    return facts


def _business_facts(text: str) -> dict[str, set[str]]:
    facts: dict[str, set[str]] = {}
    for raw_line in text.splitlines():
        line = " ".join(strip_diacritics(raw_line).split())
        values: list[str] = []

        anchor = _FACT_VALUE_RE.sub(partial(_capture_fact_value, values=values), line)
        if not values:
            continue

        anchor = " ".join(re.sub(r"[^a-z0-9<>]+", " ", anchor).split())
        words = [word for word in anchor.split() if not word.startswith("<value")]
        if not words or len(" ".join(words)) < 3:
            continue
        for slot, value in enumerate(values):
            facts.setdefault(f"{anchor} [slot {slot}]", set()).add(value)
    return facts


def _capture_fact_value(match: re.Match[str], *, values: list[str]) -> str:
    """Capture a normalized fact value without closing over a loop-local list."""
    slot = len(values)
    values.append(_normalise_fact_value(match))
    return f" <value{slot}> "


def _normalise_fact_value(match: re.Match[str]) -> str:
    value = " ".join(match.group(0).lower().split())
    if match.lastgroup == "money":
        money = _NORMALIZED_MONEY_RE.fullmatch(value)
        if money:
            return f"{_price_to_vnd(money.group(1), money.group(2)):,} VND"
    if match.lastgroup == "percent":
        number = re.search(r"\d+(?:[.,]\d+)?", value)
        if number:
            return f"{float(number.group(0).replace(',', '.')):g}%"
    if match.lastgroup == "date":
        parts = re.split(r"[/-]", value)
        if len(parts) == 3:
            year = int(parts[2])
            if year < 100:
                year += 2000
            return f"{int(parts[0]):02d}/{int(parts[1]):02d}/{year:04d}"
    return value.replace(",", ".")


def _has_content_scope_evidence(
    has_shared_price_scope: bool,
    fact_differences: list[tuple[str, set[str], set[str]]],
) -> bool:
    return bool(fact_differences or has_shared_price_scope)


def _price_facts(text: str) -> dict[str, set[int]]:
    """Extract unit/product identifiers and prices from table-like lines."""
    facts: dict[str, set[int]] = {}
    unkeyed: set[int] = set()
    vnd_table_context = _VND_TABLE_CONTEXT_RE.search(strip_diacritics(text)) is not None
    for line in text.splitlines():
        prices = _line_prices(line, vnd_table_context=vnd_table_context)
        prices.discard(0)
        if not prices:
            continue
        codes = set()
        for match in _UNIT_CODE_RE.finditer(line):
            raw_code = match.group(0).upper()
            compact_code = re.sub(r"[^A-Z0-9]", "", raw_code)
            if _NON_UNIT_CODE_RE.fullmatch(compact_code):
                continue
            codes.add(re.sub(r"[-.]+", "-", raw_code))
        if codes:
            for code in codes:
                facts.setdefault(code, set()).update(prices)
        else:
            unkeyed.update(prices)
    if unkeyed:
        facts["__DOCUMENT_PRICES__"] = unkeyed
    return facts


def _line_prices(line: str, *, vnd_table_context: bool) -> set[int]:
    prices: set[int] = set()
    compound_spans: list[tuple[int, int]] = []
    for match in _COMPOUND_PRICE_RE.finditer(line):
        compound_spans.append(match.span())
        prices.add(_price_to_vnd(match.group("billions"), "ty") + _price_to_vnd(match.group("millions"), "trieu"))

    for match in _PRICE_RE.finditer(line):
        if any(start <= match.start() and match.end() <= end for start, end in compound_spans):
            continue
        prices.add(_price_to_vnd(match.group(1), match.group(2)))

    if not prices and vnd_table_context:
        prices.update(_price_to_vnd(match.group(1), "VND") for match in _BARE_GROUPED_VND_RE.finditer(line))
    return prices


def _price_to_vnd(number: str, unit: str) -> int:
    """Thin adapter over the shared parser, kept so the regex loops above read unchanged.

    One deliberate behaviour change came with the move: this used to treat a *single*
    dot-group as thousands when the unit was triệu, so "1.500 trieu" parsed as 1.5 tỷ while
    every other parser in the codebase read it as 1.5 triệu. A single group is now a decimal
    under both profiles; only genuinely unambiguous grouping ("1.500.000") is thousands.

    Returns 0 for unparseable input, which `_price_facts` discards along with any other
    falsy price rather than recording it as a fact.
    """
    return parse_vnd(number, unit, profile=Profile.DOCUMENT) or 0


def _price_differences(
    old_text: str,
    new_text: str,
) -> list[tuple[str, set[int], set[int]]]:
    old_facts = _price_facts(old_text)
    new_facts = _price_facts(new_text)
    return _price_differences_from_facts(old_facts, new_facts)


def _price_differences_from_facts(
    old_facts: dict[str, set[int]],
    new_facts: dict[str, set[int]],
) -> list[tuple[str, set[int], set[int]]]:
    return [
        (key, old_facts.get(key, set()), new_facts.get(key, set()))
        for key in sorted(old_facts.keys() | new_facts.keys())
        if old_facts.get(key, set()) != new_facts.get(key, set())
    ]


def _rule_evidence_payload(
    price_differences: list[tuple[str, set[int], set[int]]],
    fact_differences: list[tuple[str, set[str], set[str]]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "rule": {
            "price_differences": [
                {"fact_key": key, "document_a": sorted(old), "document_b": sorted(new)}
                for key, old, new in price_differences[:20]
            ],
            "fact_differences": [
                {"fact_key": key, "document_a": sorted(old), "document_b": sorted(new)}
                for key, old, new in fact_differences[:20]
            ],
        },
    }


def _semantic_evidence_payload(assessment: SemanticConflictAssessment) -> dict[str, object]:
    return {
        "schema_version": 1,
        "semantic": assessment.model_dump(mode="json"),
    }


def _format_price_differences(
    differences: list[tuple[str, set[int], set[int]]],
) -> str:
    if not differences:
        return ""
    samples = []
    for key, old_prices, new_prices in differences[:5]:
        label = "toàn bảng" if key == "__DOCUMENT_PRICES__" else key
        old_value = "/".join(f"{value:,}" for value in sorted(old_prices))
        new_value = "/".join(f"{value:,}" for value in sorted(new_prices))
        samples.append(f" {label}: {old_value} → {new_value} VNĐ")
    return " Các mức giá thay đổi:" + ";".join(samples) + "."


def _format_fact_differences(
    differences: list[tuple[str, set[str], set[str]]],
) -> str:
    if not differences:
        return ""
    samples = []
    for anchor, old_values, new_values in differences[:5]:
        label = re.sub(r"<value\d+>", "…", anchor)[:100]
        old_value = "/".join(sorted(old_values))
        new_value = "/".join(sorted(new_values))
        samples.append(f" {label}: {old_value} → {new_value}")
    return " Các điều khoản thay đổi:" + ";".join(samples) + "."


def _read_original_text(document: Document) -> str:
    if not document.file_path:
        return ""
    response = get_minio_client().get_object(
        settings.minio_bucket_documents,
        document.file_path,
    )
    try:
        data = response.read()
    finally:
        response.close()
        response.release_conn()
    sections = parse_document(document.title, data)
    return "\n\n".join(section.text for section in sections)


def _store_original_file(
    *,
    document_id: int,
    filename: str,
    file_bytes: bytes,
    content_type: str | None,
) -> str:
    """Store the original file in MinIO; the DB keeps only the object key."""
    safe_filename = PurePath(filename).name
    object_key = f"documents/{document_id}/{uuid.uuid4().hex}-{safe_filename}"

    try:
        ensure_bucket(settings.minio_bucket_documents)

        get_minio_client().put_object(
            bucket_name=settings.minio_bucket_documents,
            object_name=object_key,
            data=BytesIO(file_bytes),
            length=len(file_bytes),
            content_type=content_type or "application/octet-stream",
        )
    except Exception as exc:
        raise DocumentIngestionError("Could not store original file in MinIO.") from exc

    return object_key
