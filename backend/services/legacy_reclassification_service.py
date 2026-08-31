"""Explicit LLM reclassification/backfill for legacy knowledge-base documents.

This service is intentionally not called by startup or ingestion.  An authenticated Admin
must first preview a bounded list of stored originals and then send back a short-lived,
signed confirmation token.  That makes the expensive model call observable and prevents a
stale browser tab from overwriting metadata that changed after the preview.

MySQL remains the metadata source of truth.  Any apply operation first quarantines the
document in Qdrant; a failure can therefore reduce availability but can never publish
half-applied metadata to retrieval.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import inspect
import json
import logging
import re
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON as SA_JSON
from sqlalchemy import or_
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.enums import (
    ConflictStatus,
    DocumentRelationType,
    DocumentReviewStatus,
    DocumentStatus,
    LegalStatus,
)
from backend.core.gemini_client import is_gemini_quota_error
from backend.models.conflict_flag import ConflictFlag
from backend.models.document import Document
from backend.models.document_relation import DocumentRelation
from backend.models.project import Project
from backend.repositories.document import get_document
from backend.schemas.document_reclassification import (
    LegacyReclassificationCandidate,
    MetadataChange,
    ProjectCandidate,
    ProjectResolution,
    ReclassificationApplyItem,
    ReclassificationApplyResult,
    ReclassificationPreviewItem,
)
from backend.services.chunking_service import chunk_sections, chunk_sections_by_classification
from backend.services.document_category_service import document_categories
from backend.services.document_classification_service import (
    DOCUMENT_CLASSIFICATION_VERSION,
    DocumentClassification,
    classify_document,
)
from backend.services.ingestion_service import (
    AI_SERVICE_QUOTA_PUBLIC_MESSAGE,
    DocumentAIQuotaExceededError,
    DocumentIngestionError,
    _conflict_scope_lock,
    _embed_and_index,
    _read_original_file,
    prepare_semantic_conflict_assessments,
    sanitize_and_scan,
    scan_conflicts_for,
)
from backend.services.parser_service import ParsedSection, parse_document
from backend.services.project_metadata_service import (
    ProjectCatalogEntry,
    classification_project_catalog,
    resolve_classified_project,
)
from backend.services.vector_store_service import delete_document_vectors, update_document_vector_metadata
from backend.utils.text import strip_diacritics
from backend.utils.time import utcnow

logger = logging.getLogger(__name__)

_TOKEN_VERSION = 1
_TOKEN_TTL_SECONDS = 30 * 60
_ALLOWED_STATUSES = frozenset({DocumentStatus.COMPLETED.value, DocumentStatus.BLOCKED.value})
_RETIRED_LEGAL_STATUSES = frozenset(
    {
        LegalStatus.NOT_YET_EFFECTIVE.value,
        LegalStatus.EXPIRED.value,
        LegalStatus.REPEALED.value,
        LegalStatus.REPLACED.value,
    }
)
_RETIREMENT_RELATIONS = frozenset(
    {
        DocumentRelationType.REPLACES.value,
        DocumentRelationType.SUPERSEDES.value,
        DocumentRelationType.REPEALS.value,
    }
)
_CLASSIFICATION_FIELDS = (
    "category",
    "categories",
    "section_classifications",
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
    "classification_confidence",
    "classification_reason",
    "conflict_facts",
)


class LegacyReclassificationError(RuntimeError):
    """A preview/apply operation could not be completed safely."""


class InvalidConfirmationTokenError(LegacyReclassificationError):
    """The preview token is invalid, expired or no longer matches the document."""


@dataclass(frozen=True)
class _ParsedOriginal:
    source_sha256: str
    raw_text: str
    sections: list[ParsedSection]


def list_reclassification_candidates(
    db: Session,
    *,
    legacy_only: bool = True,
    pending_only: bool = False,
    limit: int = 100,
) -> list[LegacyReclassificationCandidate]:
    """List bounded, safely re-readable documents; never invokes the LLM.

    ``pending_only`` is the interactive Admin flow: it deliberately selects only
    successfully parsed documents that are still waiting for metadata approval.  A
    blocked document needs its own remediation path and must not be repeatedly offered
    as though reclassification alone could approve it.
    """

    query = db.query(Document).filter(
        Document.status.in_([DocumentStatus.COMPLETED.value, DocumentStatus.BLOCKED.value]),
        Document.file_path.is_not(None),
    )
    if legacy_only and hasattr(Document, "classification_version"):
        query = query.filter(
            or_(
                Document.classification_version.is_(None),
                Document.classification_version != DOCUMENT_CLASSIFICATION_VERSION,
                Document.conflict_facts.is_(None),
                Document.conflict_facts == SA_JSON.NULL,
            )
        )
    if pending_only:
        query = query.filter(
            Document.status == DocumentStatus.COMPLETED.value,
            Document.review_status == DocumentReviewStatus.PENDING.value,
        )

    documents = query.order_by(Document.id).limit(limit).all()
    return [
        LegacyReclassificationCandidate(
            document_id=document.id,
            title=document.title,
            status=_enum_value(document.status),
            category=_enum_value(document.category),
            project_id=document.project_id,
            classification_version=getattr(document, "classification_version", None),
            classification_confidence=document.classification_confidence,
        )
        for document in documents
    ]


def preview_document_reclassification(
    db: Session,
    *,
    document_id: int,
    admin_id: int,
) -> ReclassificationPreviewItem:
    """Classify one stored original without persisting any result."""

    document = get_document(db, document_id)
    if document is None:
        return _preview_error(document_id, None, None, "Document does not exist.")

    title = document.title
    current_status = _enum_value(document.status)
    if current_status not in _ALLOWED_STATUSES:
        return _preview_error(
            document_id,
            title,
            current_status,
            "Only completed or blocked legacy documents can be reclassified.",
        )
    if not document.file_path:
        return _preview_error(document_id, title, current_status, "Document has no stored original file.")

    try:
        original = _parse_original(document)
        projects = db.query(Project).order_by(Project.id).all()
        project_catalog = classification_project_catalog(db)
        classification_units = chunk_sections(original.sections, document_category=None)
        classification = _classify_with_project_catalog(
            document.title,
            original.raw_text,
            project_catalog,
            content_units=[
                {
                    "section_index": unit.index,
                    "page": unit.page,
                    "content_type": unit.content_type,
                    "content": unit.text,
                }
                for unit in classification_units
            ],
        )
        resolution = resolve_project_candidates(
            document,
            classification,
            projects,
            project_catalog=project_catalog,
        )
        classification_data = classification.model_dump(mode="json")
        changes = _metadata_changes(document, classification)
        snapshot_sha256 = _document_snapshot_sha256(document)
        token = _encode_confirmation_token(
            {
                "version": _TOKEN_VERSION,
                "document_id": document.id,
                "admin_id": admin_id,
                "source_sha256": original.source_sha256,
                "snapshot_sha256": snapshot_sha256,
                "classification": classification_data,
                "recommended_project_id": resolution.recommended_project_id,
            }
        )
        return ReclassificationPreviewItem(
            document_id=document.id,
            title=document.title,
            status=current_status,
            source_sha256=original.source_sha256,
            suggestion=classification_data,
            changes=changes,
            project_resolution=resolution,
            confirmation_token=token,
        )
    except Exception as exc:
        logger.warning(
            "Could not preview legacy document reclassification.",
            exc_info=True,
            extra={"event": "document.legacy_reclassification.preview_failed", "document_id": document_id},
        )
        return _preview_error(document_id, title, current_status, _safe_preview_error(exc))


def apply_document_reclassification(
    db: Session,
    *,
    item: ReclassificationApplyItem,
    admin_id: int,
) -> ReclassificationApplyResult:
    """Apply one signed preview, preserving every existing quarantine decision."""

    payload = _decode_confirmation_token(item.confirmation_token)
    document_id = _token_int(payload, "document_id")
    if _token_int(payload, "admin_id") != admin_id:
        raise InvalidConfirmationTokenError("The preview belongs to a different Admin account.")

    document = get_document(db, document_id, for_update=True)
    if document is None:
        raise InvalidConfirmationTokenError("The previewed document no longer exists.")
    if _enum_value(document.status) not in _ALLOWED_STATUSES:
        raise InvalidConfirmationTokenError("The document lifecycle changed after preview; preview it again.")
    if not document.file_path:
        raise InvalidConfirmationTokenError("The document no longer has a stored original file.")
    _assert_expected_snapshot(
        document,
        str(payload.get("snapshot_sha256", "")),
        "Document metadata changed after preview; preview it again.",
    )

    try:
        classification = DocumentClassification.model_validate(payload["classification"])
    except Exception as exc:
        raise InvalidConfirmationTokenError("The preview contains invalid classification metadata.") from exc

    target_project_id = _resolve_apply_project_id(db, document, item)
    original = _parse_original(document)
    if not hmac.compare_digest(str(payload.get("source_sha256", "")), original.source_sha256):
        raise InvalidConfirmationTokenError("The stored original changed after preview; preview it again.")

    old_category = _enum_value(document.category)
    old_project_id = document.project_id
    target_category = _enum_value(classification.category)
    requires_reindex = (
        old_category != target_category
        or document_categories(document) != [str(value) for value in classification.categories]
        or (document.section_classifications or [])
        != [item.model_dump(mode="json") for item in classification.section_classifications]
        or old_project_id != target_project_id
        or _enum_value(document.review_status) == DocumentReviewStatus.PENDING.value
    )
    was_blocked = _enum_value(document.status) == DocumentStatus.BLOCKED.value

    chunks = None
    if requires_reindex:
        chunks = chunk_sections_by_classification(
            original.sections,
            primary_category=str(classification.category),
            section_classifications=[item.model_dump(mode="json") for item in classification.section_classifications],
        )
        if not chunks:
            raise LegacyReclassificationError("The proposed category produced no indexable chunks.")

    # Quarantine the indexed version under its pre-reclassification labels.
    update_document_vector_metadata(
        document.id,
        review_status=_enum_value(document.review_status),
        legal_status=_enum_value(document.legal_status),
        category=old_category,
        categories=document_categories(document),
        visibility=_enum_value(document.visibility),
        is_current=False,
    )
    document.is_current = False
    quarantined_snapshot_sha256 = _document_snapshot_sha256(document)
    db.commit()

    conflict_ids: tuple[int, ...] = ()
    duplicate_ids: tuple[int, ...] = ()
    try:
        document = get_document(db, document_id, for_update=True)
        if document is None:  # pragma: no cover - deletion also needs the row lock
            raise LegacyReclassificationError("Document disappeared while applying metadata.")
        _assert_expected_snapshot(
            document,
            quarantined_snapshot_sha256,
            "Document metadata changed while it was being quarantined; preview it again.",
        )

        _apply_classification(document, classification, target_project_id=target_project_id, admin_id=admin_id)
        document.is_current = False

        if requires_reindex:
            if chunks is None:
                raise LegacyReclassificationError("Reindexing requires parsed document chunks.")
            delete_document_vectors(document.id)
            _embed_and_index(document, chunks, is_current=False)

        staged_snapshot_sha256 = _document_snapshot_sha256(document)
        db.commit()

        if was_blocked:
            document = _finalize_vector_publish(
                db,
                document_id=document_id,
                expected_snapshot_sha256=staged_snapshot_sha256,
            )
        else:
            semantic_assessments = prepare_semantic_conflict_assessments(
                db,
                document,
                raw_text=original.raw_text,
            )
            with _conflict_scope_lock(db, document):
                document = get_document(db, document_id, for_update=True)
                if document is None:  # pragma: no cover - deletion also needs the row lock
                    raise LegacyReclassificationError("Document disappeared before conflict scanning.")
                _assert_expected_snapshot(
                    document,
                    staged_snapshot_sha256,
                    "Document metadata changed before conflict scanning; preview it again.",
                )
                outcome = scan_conflicts_for(
                    db,
                    document,
                    raw_text=original.raw_text,
                    semantic_assessments=semantic_assessments,
                    commit=False,
                )
                conflict_ids = outcome.conflict_ids
                duplicate_ids = outcome.duplicate_document_ids

                if duplicate_ids:
                    document.status = DocumentStatus.BLOCKED
                    document.review_status = DocumentReviewStatus.REJECTED
                    duplicate_text = ", ".join(str(value) for value in duplicate_ids)
                    document.classification_reason = (
                        f"{document.classification_reason or ''} Exact duplicate of document(s): {duplicate_text}."
                    ).strip()

                document.is_current = bool(
                    not conflict_ids
                    and not duplicate_ids
                    and _enum_value(document.review_status) == DocumentReviewStatus.APPROVED.value
                    and _enum_value(document.legal_status) not in _RETIRED_LEGAL_STATUSES
                    and not _has_open_conflict(db, document.id)
                    and not _is_retired_by_relation(db, document.id)
                )
                decision_snapshot_sha256 = _document_snapshot_sha256(document)
                db.commit()

                document = _finalize_vector_publish(
                    db,
                    document_id=document_id,
                    expected_snapshot_sha256=decision_snapshot_sha256,
                )
    except Exception as exc:
        db.rollback()
        logger.exception(
            "Applying legacy document reclassification failed; retrieval requires reconciliation.",
            extra={
                "event": "document.legacy_reclassification.apply_failed",
                "document_id": document_id,
                "from_category": old_category,
                "to_category": target_category,
                "from_project_id": old_project_id,
                "to_project_id": target_project_id,
            },
        )
        if is_gemini_quota_error(exc):
            raise DocumentAIQuotaExceededError() from exc
        raise

    db.refresh(document)
    return ReclassificationApplyResult(
        document_id=document.id,
        title=document.title,
        status=_enum_value(document.status),
        category=_enum_value(document.category),
        project_id=document.project_id,
        is_current=bool(document.is_current),
        reindexed=requires_reindex,
        conflict_ids=list(conflict_ids),
        duplicate_document_ids=list(duplicate_ids),
    )


def _finalize_vector_publish(
    db: Session,
    *,
    document_id: int,
    expected_snapshot_sha256: str,
) -> Document:
    """Publish only a freshly locked DB state, then mark the LLM backfill complete."""

    document = get_document(db, document_id, for_update=True)
    if document is None:  # pragma: no cover - deletion also needs the row lock
        raise LegacyReclassificationError("Document disappeared before vector synchronisation.")
    _assert_expected_snapshot(
        document,
        expected_snapshot_sha256,
        "Document metadata changed before vector synchronisation; preview it again.",
    )

    update_document_vector_metadata(
        document.id,
        review_status=_enum_value(document.review_status),
        legal_status=_enum_value(document.legal_status),
        category=_enum_value(document.category),
        categories=document_categories(document),
        visibility=_enum_value(document.visibility),
        is_current=bool(document.is_current),
    )

    document.classification_version = DOCUMENT_CLASSIFICATION_VERSION
    db.commit()
    db.refresh(document)
    return document


def _assert_expected_snapshot(document: Document, expected_sha256: str, message: str) -> None:
    if not hmac.compare_digest(expected_sha256, _document_snapshot_sha256(document)):
        raise InvalidConfirmationTokenError(message)


def resolve_project_candidates(
    document: Document,
    classification: DocumentClassification,
    projects: list[Project],
    *,
    project_catalog: list[ProjectCatalogEntry],
) -> ProjectResolution:
    """Resolve catalogue IDs from explicit LLM output and canonical project aliases.

    The resolver only recommends; it never writes.  Exact catalogue IDs and exact
    subdivision-name aliases are strong signals. Filename matches are weaker and are
    returned for an Admin to inspect rather than silently assigning a project.
    """

    project_by_id = {project.id: project for project in projects}
    llm_project_id = getattr(classification, "project_id", None)
    canonical_resolution = resolve_classified_project(
        selected_project_id=document.project_id,
        suggested_project_id=llm_project_id,
        subdivision_names=classification.subdivision_names,
        catalog=project_catalog,
    )
    warning = canonical_resolution.note
    scored: dict[str, ProjectCandidate] = {}

    if llm_project_id:
        project = project_by_id.get(str(llm_project_id))
        if project is None:
            warning = f"LLM suggested unknown project_id '{llm_project_id}'."
        else:
            scored[project.id] = ProjectCandidate(
                project_id=project.id,
                project_name=project.name,
                confidence=1.0,
                reason="LLM selected an exact ID from the current project catalogue.",
            )

    aliases = {project.id: _project_aliases(project) for project in projects}
    subdivision_values = [_normalise(value) for value in (classification.subdivision_names or [])]
    for project in projects:
        if any(value and value in aliases[project.id] for value in subdivision_values):
            _keep_best_candidate(
                scored,
                ProjectCandidate(
                    project_id=project.id,
                    project_name=project.name,
                    confidence=0.95,
                    reason="An extracted subdivision name exactly matches a canonical project alias.",
                ),
            )

    title_normalised = _normalise(document.title)
    title_compact = title_normalised.replace(" ", "")
    for project in projects:
        matching_aliases = [
            alias
            for alias in aliases[project.id]
            if len(alias) >= 5 and (f" {alias} " in f" {title_normalised} " or alias.replace(" ", "") in title_compact)
        ]
        if matching_aliases:
            longest = max(matching_aliases, key=len)
            _keep_best_candidate(
                scored,
                ProjectCandidate(
                    project_id=project.id,
                    project_name=project.name,
                    confidence=0.80,
                    reason=f"Filename contains canonical project alias '{longest}'.",
                ),
            )

    candidates = sorted(scored.values(), key=lambda item: (-item.confidence, -len(item.project_name), item.project_id))
    recommended = canonical_resolution.project_id
    requires_confirmation = bool(
        canonical_resolution.requires_admin_review
        or recommended != document.project_id
        or warning is not None
        or len(candidates) > 1
    )
    return ProjectResolution(
        stored_project_id=document.project_id,
        llm_project_id=str(llm_project_id) if llm_project_id else None,
        recommended_project_id=recommended,
        candidates=candidates,
        requires_confirmation=requires_confirmation,
        warning=warning,
    )


def _classify_with_project_catalog(
    filename: str,
    raw_text: str,
    project_catalog: Sequence[Mapping[str, object]],
    *,
    content_units: Sequence[Mapping[str, object]] | None = None,
) -> DocumentClassification:
    """Use the catalogue-aware classifier when available, remaining test-compatible."""

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
    return classify_document(filename, raw_text, **kwargs)


def _parse_original(document: Document) -> _ParsedOriginal:
    try:
        file_bytes = _read_original_file(str(document.file_path))
        parsed = parse_document(document.title, file_bytes)
        sections = [
            ParsedSection(
                text=cleaned,
                page=section.page,
                content_type=section.content_type,
                block_offsets=section.block_offsets,
            )
            for section in parsed
            if (cleaned := section.text.replace("\x00", "").strip())
        ]
        raw_text = sanitize_and_scan("\n\n".join(section.text for section in sections))
    except DocumentIngestionError:
        raise
    except Exception as exc:
        raise LegacyReclassificationError("Could not read and parse the stored original file.") from exc

    return _ParsedOriginal(
        source_sha256=hashlib.sha256(file_bytes).hexdigest(),
        raw_text=raw_text,
        sections=sections,
    )


def _apply_classification(
    document: Document,
    classification: DocumentClassification,
    *,
    target_project_id: str | None,
    admin_id: int,
) -> None:
    for field_name in (
        "category",
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
    ):
        setattr(document, field_name, getattr(classification, field_name))

    document.categories = [str(value) for value in classification.categories]
    document.section_classifications = [item.model_dump(mode="json") for item in classification.section_classifications]

    document.project_id = target_project_id
    document.conflict_facts = [fact.model_dump(mode="json") for fact in classification.conflict_facts]
    document.classification_confidence = classification.confidence
    document.classification_reason = classification.reason
    applied_at = utcnow().replace(microsecond=0)
    document.classified_at = applied_at
    if hasattr(document, "classification_requires_admin_review"):
        document.classification_requires_admin_review = classification.requires_admin_review

    if _enum_value(document.status) != DocumentStatus.BLOCKED.value:
        document.review_status = DocumentReviewStatus.APPROVED
    document.reviewed_by = admin_id
    document.reviewed_at = applied_at


def _resolve_apply_project_id(db: Session, document: Document, item: ReclassificationApplyItem) -> str | None:
    if item.project_action == "keep":
        return document.project_id
    if item.project_action == "clear":
        return None

    project_id = str(item.project_id)
    if db.get(Project, project_id) is None:
        raise LegacyReclassificationError(f"project_id '{project_id}' does not exist in the project catalogue.")
    return project_id


def _metadata_changes(document: Document, classification: DocumentClassification) -> dict[str, MetadataChange]:
    suggested = classification.model_dump(mode="json")
    stored = {
        "category": _enum_value(document.category),
        "categories": document_categories(document),
        "section_classifications": document.section_classifications or [],
        "subcategory": document.subcategory,
        "subdivision_names": document.subdivision_names,
        "building_codes": document.building_codes,
        "unit_types": document.unit_types,
        "applicable_area": document.applicable_area,
        "document_summary": document.document_summary,
        "version_label": document.version_label,
        "issued_date": _json_value(document.issued_date),
        "effective_date": _json_value(document.effective_date),
        "expiry_date": _json_value(document.expiry_date),
        "applicable_period": document.applicable_period,
        "legal_document_type": document.legal_document_type,
        "legal_document_number": document.legal_document_number,
        "legal_issuer": document.legal_issuer,
        "legal_domain": document.legal_domain,
        "legal_status": _enum_value(document.legal_status),
        "classification_confidence": document.classification_confidence,
        "classification_reason": document.classification_reason,
        "conflict_facts": document.conflict_facts,
    }
    suggestions_by_stored_name = {
        **suggested,
        "classification_confidence": suggested.get("confidence"),
        "classification_reason": suggested.get("reason"),
    }

    return {
        field_name: MetadataChange(stored=stored[field_name], suggested=suggestions_by_stored_name.get(field_name))
        for field_name in _CLASSIFICATION_FIELDS
        if _json_value(stored[field_name]) != _json_value(suggestions_by_stored_name.get(field_name))
    }


def _document_snapshot_sha256(document: Document) -> str:
    snapshot = {
        "id": document.id,
        "title": document.title,
        "file_path": document.file_path,
        "status": _enum_value(document.status),
        "project_id": document.project_id,
        "visibility": _enum_value(document.visibility),
        "category": _enum_value(document.category),
        "categories": document_categories(document),
        "section_classifications": document.section_classifications or [],
        "subcategory": document.subcategory,
        "subdivision_names": document.subdivision_names,
        "building_codes": document.building_codes,
        "unit_types": document.unit_types,
        "applicable_area": document.applicable_area,
        "document_summary": document.document_summary,
        "version_label": document.version_label,
        "issued_date": _json_value(document.issued_date),
        "effective_date": _json_value(document.effective_date),
        "expiry_date": _json_value(document.expiry_date),
        "applicable_period": document.applicable_period,
        "legal_document_type": document.legal_document_type,
        "legal_document_number": document.legal_document_number,
        "legal_issuer": document.legal_issuer,
        "legal_domain": document.legal_domain,
        "legal_status": _enum_value(document.legal_status),
        "review_status": _enum_value(document.review_status),
        "classification_confidence": document.classification_confidence,
        "classification_reason": document.classification_reason,
        "conflict_facts": document.conflict_facts,
        "classified_at": _json_value(document.classified_at),
        "is_current": bool(document.is_current),
    }
    if hasattr(document, "classification_requires_admin_review"):
        snapshot["classification_requires_admin_review"] = document.classification_requires_admin_review
    if hasattr(document, "classification_version"):
        snapshot["classification_version"] = document.classification_version
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _project_aliases(project: Project) -> set[str]:
    raw_aliases: list[str] = [project.id, project.name]
    if " - " in project.name:
        raw_aliases.append(project.name.split(" - ", 1)[0].strip())

    return {_normalise(value) for value in raw_aliases if value and _normalise(value)}


def _normalise(value: str) -> str:
    value = strip_diacritics(value).lower().replace("đ", "d")
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _keep_best_candidate(scored: dict[str, ProjectCandidate], candidate: ProjectCandidate) -> None:
    current = scored.get(candidate.project_id)
    if current is None or candidate.confidence > current.confidence:
        scored[candidate.project_id] = candidate


def _has_open_conflict(db: Session, document_id: int) -> bool:
    return (
        db.query(ConflictFlag.id)
        .filter(
            ConflictFlag.status == ConflictStatus.OPEN,
            or_(ConflictFlag.document_id_a == document_id, ConflictFlag.document_id_b == document_id),
        )
        .first()
        is not None
    )


def _is_retired_by_relation(db: Session, document_id: int) -> bool:
    return (
        db.query(DocumentRelation.id)
        .filter(
            DocumentRelation.target_document_id == document_id,
            DocumentRelation.review_status == DocumentReviewStatus.APPROVED,
            DocumentRelation.relation_type.in_(_RETIREMENT_RELATIONS),
        )
        .first()
        is not None
    )


def _encode_confirmation_token(payload: dict[str, Any]) -> str:
    now = int(time.time())
    token_payload = {**payload, "issued_at": now, "expires_at": now + _TOKEN_TTL_SECONDS}
    raw = json.dumps(token_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    encoded = _b64encode(raw)
    signature = hmac.new(settings.secret_key.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def _decode_confirmation_token(token: str) -> dict[str, Any]:
    try:
        encoded, supplied_signature = token.split(".", 1)
        expected_signature = hmac.new(
            settings.secret_key.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256
        ).digest()
        if not hmac.compare_digest(_b64decode(supplied_signature), expected_signature):
            raise InvalidConfirmationTokenError("Invalid reclassification confirmation token.")
        payload = json.loads(_b64decode(encoded))
    except InvalidConfirmationTokenError:
        raise
    except Exception as exc:
        raise InvalidConfirmationTokenError("Invalid reclassification confirmation token.") from exc

    if payload.get("version") != _TOKEN_VERSION:
        raise InvalidConfirmationTokenError("Unsupported reclassification preview version.")
    if int(payload.get("expires_at", 0)) < int(time.time()):
        raise InvalidConfirmationTokenError("The reclassification preview expired; preview it again.")
    return payload


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _token_int(payload: dict[str, Any], key: str) -> int:
    try:
        return int(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidConfirmationTokenError(f"The preview token has no valid {key}.") from exc


def _json_value(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return value


def _enum_value(value: Any) -> str:
    return str(value.value if hasattr(value, "value") else value)


def _preview_error(
    document_id: int,
    title: str | None,
    status: str | None,
    error: str,
) -> ReclassificationPreviewItem:
    return ReclassificationPreviewItem(
        document_id=document_id,
        title=title or "",
        status=status or "unknown",
        error=error,
    )


def _safe_preview_error(exc: Exception) -> str:
    if is_gemini_quota_error(exc):
        return AI_SERVICE_QUOTA_PUBLIC_MESSAGE
    if isinstance(exc, (DocumentIngestionError, LegacyReclassificationError)):
        return str(exc)
    return "Could not classify the stored original. Check server logs."
