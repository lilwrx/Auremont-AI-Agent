from datetime import datetime
from typing import Any, Literal

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from backend.core.enums import (
    ConflictStatus,
    DocumentRelationType,
    DocumentReviewStatus,
    DocumentStatus,
    LegalStatus,
)
from backend.models.conflict_flag import ConflictFlag
from backend.models.document import Document
from backend.models.document_relation import DocumentRelation
from backend.services.vector_store_service import document_vector_metadata_snapshot
from backend.utils.time import utcnow

DetectionMethod = Literal["rule", "llm", "hybrid"]
_DETECTION_METHODS = frozenset({"rule", "llm", "hybrid"})


def create_conflict(
    db: Session,
    document_id_a: int,
    document_id_b: int,
    description: str | None,
    *,
    detection_method: DetectionMethod = "rule",
    confidence: float | None = None,
    similarity_score: float | None = None,
    conflict_type: str | None = None,
    evidence: dict[str, Any] | None = None,
    analysis_version: str | None = None,
    commit: bool = True,
) -> ConflictFlag:
    """Create one open flag per document pair.

    Conflict scans may be retried, and a document can be scanned manually after
    ingestion. Returning the existing open flag keeps those retries idempotent even
    without a schema migration for a canonical pair key. A later semantic scan enriches
    the same open flag instead of creating a duplicate. None means "not measured" and
    therefore never clears evidence already persisted by an earlier detector.
    """
    _validate_analysis_metadata(detection_method, confidence, similarity_score)
    if document_id_a > document_id_b:
        document_id_a, document_id_b = document_id_b, document_id_a
        evidence = _swap_evidence_sides(evidence)

    latest = (
        db.query(ConflictFlag)
        .filter(
            or_(
                and_(
                    ConflictFlag.document_id_a == document_id_a,
                    ConflictFlag.document_id_b == document_id_b,
                ),
                and_(
                    ConflictFlag.document_id_a == document_id_b,
                    ConflictFlag.document_id_b == document_id_a,
                ),
            ),
        )
        .order_by(ConflictFlag.id.desc())
        .with_for_update()
        .first()
    )
    if latest is not None and latest.status != ConflictStatus.OPEN:
        return latest

    existing = latest
    if existing is not None:
        incoming_is_reversed = existing.document_id_a == document_id_b and existing.document_id_b == document_id_a
        if incoming_is_reversed:
            evidence = _swap_evidence_sides(evidence)
        changed = _enrich_conflict(
            existing,
            description=description,
            detection_method=detection_method,
            confidence=confidence,
            similarity_score=similarity_score,
            conflict_type=conflict_type,
            evidence=evidence,
            analysis_version=analysis_version,
        )
        if changed:
            if commit:
                db.commit()
                db.refresh(existing)
            else:
                db.flush()
        return existing

    conflict = ConflictFlag(
        document_id_a=document_id_a,
        document_id_b=document_id_b,
        description=description,
        detection_method=detection_method,
        confidence=confidence,
        similarity_score=similarity_score,
        conflict_type=conflict_type,
        evidence=evidence,
        analysis_version=analysis_version,
        status=ConflictStatus.OPEN,
    )
    db.add(conflict)
    if commit:
        db.commit()
        db.refresh(conflict)
    else:
        db.flush()
    return conflict


def _validate_analysis_metadata(
    detection_method: str,
    confidence: float | None,
    similarity_score: float | None,
) -> None:
    if detection_method not in _DETECTION_METHODS:
        raise ValueError(f"Unsupported conflict detection method: {detection_method!r}.")
    for field_name, value in (("confidence", confidence), ("similarity_score", similarity_score)):
        if value is not None and not 0 <= value <= 1:
            raise ValueError(f"{field_name} must be between 0 and 1.")


def _merged_detection_method(current: str | None, incoming: DetectionMethod) -> DetectionMethod:
    if current in (None, incoming):
        return incoming
    if current == "hybrid" or incoming == "hybrid":
        return "hybrid"
    if current in _DETECTION_METHODS:
        return "hybrid"
    return incoming


def _merge_evidence(current: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """Merge detector evidence without discarding facts collected by another source."""

    if current is None:
        return dict(incoming)

    merged: dict[str, Any] = dict(current)
    for key, incoming_value in incoming.items():
        if key in {"rule", "semantic"}:
            merged[key] = incoming_value
            continue
        current_value = merged.get(key)
        if isinstance(current_value, dict) and isinstance(incoming_value, dict):
            merged[key] = _merge_evidence(current_value, incoming_value)
        elif isinstance(current_value, list) and isinstance(incoming_value, list):
            merged[key] = [*current_value]
            for value in incoming_value:
                if value not in merged[key]:
                    merged[key].append(value)
        else:
            merged[key] = incoming_value
    return merged


_EVIDENCE_SIDE_KEY_PAIRS = (
    ("document_a", "document_b"),
    ("document_id_a", "document_id_b"),
    ("quote_a", "quote_b"),
    ("claim_a", "claim_b"),
    ("scope_a", "scope_b"),
    ("effective_period_a", "effective_period_b"),
)


def _swap_evidence_sides(value: Any) -> Any:
    """Recursively map incoming A/B evidence to the persisted pair orientation."""

    if isinstance(value, list):
        return [_swap_evidence_sides(item) for item in value]
    if not isinstance(value, dict):
        return value

    swapped = {key: _swap_evidence_sides(item) for key, item in value.items()}
    for key_a, key_b in _EVIDENCE_SIDE_KEY_PAIRS:
        has_a = key_a in swapped
        has_b = key_b in swapped
        if not has_a and not has_b:
            continue
        value_a = swapped.pop(key_a, None)
        value_b = swapped.pop(key_b, None)
        if has_b:
            swapped[key_a] = value_b
        if has_a:
            swapped[key_b] = value_a
    return swapped


def _enrich_conflict(
    conflict: ConflictFlag,
    *,
    description: str | None,
    detection_method: DetectionMethod,
    confidence: float | None,
    similarity_score: float | None,
    conflict_type: str | None,
    evidence: dict[str, Any] | None,
    analysis_version: str | None,
) -> bool:
    updates: dict[str, Any] = {
        "description": description,
        "confidence": confidence,
        "similarity_score": similarity_score,
        "conflict_type": conflict_type,
        "analysis_version": analysis_version,
    }
    merged_method = _merged_detection_method(conflict.detection_method, detection_method)
    changed = merged_method != conflict.detection_method
    conflict.detection_method = merged_method

    for field_name, value in updates.items():
        if value is not None and getattr(conflict, field_name) != value:
            setattr(conflict, field_name, value)
            changed = True

    if evidence is not None:
        merged_evidence = _merge_evidence(conflict.evidence, evidence)
        if merged_evidence != conflict.evidence:
            conflict.evidence = merged_evidence
            changed = True
    return changed


def list_open_conflicts(db: Session) -> list[ConflictFlag]:
    return db.query(ConflictFlag).filter(ConflictFlag.status == ConflictStatus.OPEN).all()


def resolve_conflict(
    db: Session,
    conflict_id: int,
    keep_document_id: int,
    resolved_by: int | None = None,
    *,
    commit: bool = True,
) -> tuple[ConflictFlag, Document, Document, dict[int, dict[str, object]]]:
    """Close a conflict flag: keep one document, disable the other.

    `keep_document_id` must be one of the flag's two documents — otherwise the
    Admin's decision would be applied to the wrong document.

    The chosen document becomes current and approved because this endpoint records an
    authenticated Admin decision. The caller may pass ``commit=False`` to synchronise
    both Qdrant payloads before committing the MySQL transaction.
    """
    seed = db.query(ConflictFlag).filter(ConflictFlag.id == conflict_id).first()
    if seed is None:
        raise ValueError(f"ConflictFlag with id={conflict_id} not found.")

    seed_pair = (seed.document_id_a, seed.document_id_b)
    related_flags = (
        db.query(ConflictFlag)
        .filter(
            or_(
                ConflictFlag.document_id_a.in_(seed_pair),
                ConflictFlag.document_id_b.in_(seed_pair),
            )
        )
        .order_by(ConflictFlag.id)
        .populate_existing()
        .with_for_update()
        .all()
    )
    conflict = next((flag for flag in related_flags if flag.id == conflict_id), None)
    if conflict is None:
        raise ValueError(f"ConflictFlag with id={conflict_id} not found.")
    if conflict.status != ConflictStatus.OPEN:
        raise ValueError(f"ConflictFlag with id={conflict_id} has already been resolved.")

    pair = (conflict.document_id_a, conflict.document_id_b)
    if keep_document_id not in pair:
        raise ValueError(f"keep_document_id={keep_document_id} is not part of conflict {conflict_id} {pair}.")

    superseded_id = conflict.document_id_b if keep_document_id == conflict.document_id_a else conflict.document_id_a
    retirement_relations = (
        db.query(DocumentRelation)
        .filter(
            DocumentRelation.target_document_id.in_(pair),
            DocumentRelation.relation_type.in_(
                [
                    DocumentRelationType.REPLACES,
                    DocumentRelationType.SUPERSEDES,
                    DocumentRelationType.REPEALS,
                ]
            ),
        )
        .order_by(DocumentRelation.id)
        .populate_existing()
        .with_for_update()
        .all()
    )
    retired_document_ids = {
        relation.target_document_id
        for relation in retirement_relations
        if relation.review_status == DocumentReviewStatus.APPROVED
    }
    documents = (
        db.query(Document)
        .filter(Document.id.in_(sorted(pair)))
        .order_by(Document.id)
        .populate_existing()
        .with_for_update()
        .all()
    )
    documents_by_id = {document.id: document for document in documents}
    kept = documents_by_id.get(keep_document_id)
    superseded = documents_by_id.get(superseded_id)
    if kept is None or superseded is None:
        raise ValueError("One or both documents in this conflict no longer exist.")
    if kept.id in retired_document_ids or kept.legal_status in {
        LegalStatus.NOT_YET_EFFECTIVE,
        LegalStatus.EXPIRED,
        LegalStatus.REPEALED,
        LegalStatus.REPLACED,
    }:
        raise ValueError(f"Document {keep_document_id} is retired and not eligible to win a conflict.")
    if kept.status != DocumentStatus.COMPLETED:
        raise ValueError(f"Document {keep_document_id} is not an active completed document.")

    previous_vector_metadata: dict[int, dict[str, object]] = {
        document.id: document_vector_metadata_snapshot(document) for document in documents
    }

    superseded.status = DocumentStatus.BLOCKED
    superseded.is_current = False

    resolved_at = utcnow()
    conflict.status = ConflictStatus.RESOLVED
    conflict.resolved_at = resolved_at
    conflict.resolved_by = resolved_by

    _resolve_open_conflicts_between_blocked_documents(
        db,
        newly_blocked_document_id=superseded.id,
        resolving_conflict_id=conflict.id,
        resolved_by=resolved_by,
        resolved_at=resolved_at,
    )

    has_other_open_conflict = (
        db.query(ConflictFlag.id)
        .filter(
            ConflictFlag.id != conflict_id,
            ConflictFlag.status == ConflictStatus.OPEN,
            or_(
                ConflictFlag.document_id_a == kept.id,
                ConflictFlag.document_id_b == kept.id,
            ),
        )
        .with_for_update()
        .first()
        is not None
    )
    kept.is_current = not has_other_open_conflict
    if kept.review_status != DocumentReviewStatus.APPROVED:
        kept.review_status = DocumentReviewStatus.APPROVED
        kept.reviewed_by = resolved_by
        kept.reviewed_at = utcnow()

    if commit:
        db.commit()
        db.refresh(conflict)
        db.refresh(kept)
        db.refresh(superseded)
    else:
        db.flush()
    return conflict, kept, superseded, previous_vector_metadata


def dismiss_conflict(
    db: Session,
    conflict_id: int,
    resolved_by: int | None = None,
    *,
    commit: bool = True,
) -> ConflictFlag:
    """Close a conflict flag while keeping both documents as-is.

    Used when the Admin decides the two sources are not actually in conflict
    (e.g. they apply to different scopes or periods), so neither document
    should be blocked or have its `is_current` flag touched.
    """
    conflict = db.query(ConflictFlag).filter(ConflictFlag.id == conflict_id).with_for_update().first()
    if conflict is None:
        raise ValueError(f"ConflictFlag with id={conflict_id} not found.")
    if conflict.status != ConflictStatus.OPEN:
        raise ValueError(f"ConflictFlag with id={conflict_id} has already been resolved.")

    conflict.status = ConflictStatus.RESOLVED
    conflict.resolved_at = utcnow()
    conflict.resolved_by = resolved_by

    if commit:
        db.commit()
        db.refresh(conflict)
    else:
        db.flush()
    return conflict


def _resolve_open_conflicts_between_blocked_documents(
    db: Session,
    *,
    newly_blocked_document_id: int,
    resolving_conflict_id: int,
    resolved_by: int | None,
    resolved_at: datetime,
) -> None:
    """Close stale graph edges after both endpoints have become BLOCKED."""
    related = (
        db.query(ConflictFlag)
        .filter(
            ConflictFlag.id != resolving_conflict_id,
            ConflictFlag.status == ConflictStatus.OPEN,
            or_(
                ConflictFlag.document_id_a == newly_blocked_document_id,
                ConflictFlag.document_id_b == newly_blocked_document_id,
            ),
        )
        .order_by(ConflictFlag.id)
        .populate_existing()
        .with_for_update()
        .all()
    )
    if not related:
        return

    other_ids = {
        flag.document_id_b if flag.document_id_a == newly_blocked_document_id else flag.document_id_a
        for flag in related
    }
    blocked_other_ids = {
        document_id
        for (document_id,) in db.query(Document.id)
        .filter(
            Document.id.in_(other_ids),
            Document.status == DocumentStatus.BLOCKED,
        )
        .order_by(Document.id)
        .with_for_update()
        .all()
    }

    for flag in related:
        other_id = flag.document_id_b if flag.document_id_a == newly_blocked_document_id else flag.document_id_a
        if other_id in blocked_other_ids:
            flag.status = ConflictStatus.RESOLVED
            flag.resolved_at = resolved_at
            flag.resolved_by = resolved_by
