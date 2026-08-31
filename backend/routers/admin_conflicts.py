import logging
from typing import cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.deps import require_role
from backend.core.enums import ConflictStatus, UserRole
from backend.core.mysql_client import get_db
from backend.models.conflict_flag import ConflictFlag
from backend.models.document import Document
from backend.models.project import Project
from backend.models.user import User
from backend.repositories.conflict_flag import dismiss_conflict, list_open_conflicts, resolve_conflict
from backend.repositories.document import get_document
from backend.schemas.conflict_flag import (
    ConflictDetailResponse,
    ConflictDetectionMethod,
    ConflictDocumentSummary,
    ConflictFlagResponse,
    ConflictResolveRequest,
)
from backend.services.cache_service import clear_cache
from backend.services.conflict_severity_service import ConflictSeverity, classify_conflict_severity
from backend.services.vector_store_service import (
    VectorStoreError,
    log_and_swallow_restore_failure,
    restore_document_vector_metadata,
    sync_document_vector_metadata,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin/conflicts", tags=["Admin Conflicts"], dependencies=[Depends(require_role(UserRole.ADMIN))]
)


def _severity(flag: ConflictFlag) -> ConflictSeverity:
    return classify_conflict_severity(
        detection_method=flag.detection_method,
        confidence=flag.confidence,
        conflict_type=flag.conflict_type,
        evidence=flag.evidence,
    )


def _document_summary(document: Document) -> ConflictDocumentSummary:
    return ConflictDocumentSummary(
        id=document.id,
        title=document.title,
        project_id=document.project_id,
        version_label=document.version_label,
        issued_date=document.issued_date,
        effective_date=document.effective_date,
        uploaded_at=document.uploaded_at,
        category=str(document.category),
        visibility=str(document.visibility),
        summary=document.document_summary,
        classification_reason=document.classification_reason,
    )


@router.get("", response_model=list[ConflictDetailResponse])
async def get_conflicts(db: Session = Depends(get_db)) -> list[ConflictDetailResponse]:
    """conflicting documents (e.g. two price-list versions of the same project)."""
    flags = list_open_conflicts(db)
    document_ids = {document_id for flag in flags for document_id in (flag.document_id_a, flag.document_id_b)}
    documents = (
        {document.id: document for document in db.query(Document).filter(Document.id.in_(document_ids)).all()}
        if document_ids
        else {}
    )
    project_ids = {document.project_id for document in documents.values() if document.project_id}
    projects = (
        {project.id: project for project in db.query(Project).filter(Project.id.in_(project_ids)).all()}
        if project_ids
        else {}
    )

    result = []
    for flag in flags:
        document_a = documents.get(flag.document_id_a)
        document_b = documents.get(flag.document_id_b)
        if document_a is None or document_b is None:
            logger.error(
                "Conflict %s refers to a missing document.",
                flag.id,
                extra={"event": "conflict.document_missing", "conflict_id": flag.id},
            )
            continue
        project_id = document_b.project_id or document_a.project_id
        result.append(
            ConflictDetailResponse(
                id=flag.id,
                document_id_a=flag.document_id_a,
                document_id_b=flag.document_id_b,
                description=flag.description,
                detection_method=cast(ConflictDetectionMethod, flag.detection_method),
                confidence=flag.confidence,
                similarity_score=flag.similarity_score,
                conflict_type=flag.conflict_type,
                severity=_severity(flag),
                evidence=flag.evidence,
                analysis_version=flag.analysis_version,
                status=ConflictStatus(flag.status),
                created_at=flag.created_at,
                resolved_by=flag.resolved_by,
                resolved_at=flag.resolved_at,
                project_id=project_id,
                project_name=projects[project_id].name if project_id in projects else None,
                document_a=_document_summary(document_a),
                document_b=_document_summary(document_b),
            )
        )
    return result


@router.post("/{conflict_id}/resolve", response_model=ConflictFlagResponse)
async def resolve_conflict_flag(
    conflict_id: int,
    payload: ConflictResolveRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> ConflictFlagResponse:
    """Keep the Admin's chosen document and atomically disable the other one."""
    attempted_vector_ids: set[int] = set()
    previous_vector_metadata: dict[int, dict[str, object]] = {}
    try:
        conflict, kept, superseded, previous_vector_metadata = resolve_conflict(
            db,
            conflict_id,
            keep_document_id=payload.keep_document_id,
            resolved_by=admin.id,
            commit=False,
        )
    except ValueError as exc:
        db.rollback()
        if "not part of conflict" in str(exc):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        if (
            "already been resolved" in str(exc)
            or "not an active completed document" in str(exc)
            or "not eligible to win a conflict" in str(exc)
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conflict could not be prepared for resolution.",
        ) from exc

    try:
        for document in (superseded, kept):
            attempted_vector_ids.add(document.id)
            sync_document_vector_metadata(document, is_current=False)
    except VectorStoreError as exc:
        try:
            _restore_vector_metadata(previous_vector_metadata, attempted_vector_ids)
        finally:
            db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conflict was not resolved because document retrieval metadata could not be synchronised.",
        ) from exc

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conflict endpoints remain quarantined because the MySQL commit outcome could not be confirmed.",
        ) from exc

    try:
        refreshed_winner = get_document(db, kept.id, for_update=True)
        if refreshed_winner is None:
            raise ValueError("The selected conflict winner no longer exists.")
        kept = refreshed_winner
        sync_document_vector_metadata(kept)
        db.commit()
    except (VectorStoreError, SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conflict was resolved in MySQL, but the winner remains quarantined until synchronisation is retried.",
        ) from exc

    db.refresh(conflict)
    clear_cache()
    return ConflictFlagResponse.model_validate(conflict).model_copy(update={"severity": _severity(conflict)})


@router.post("/{conflict_id}/dismiss", response_model=ConflictFlagResponse)
async def dismiss_conflict_flag(
    conflict_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> ConflictFlagResponse:
    """Close a conflict without blocking either document — both keep participating in RAG."""
    try:
        conflict = dismiss_conflict(db, conflict_id, resolved_by=admin.id)
    except ValueError as exc:
        db.rollback()
        if "already been resolved" in str(exc):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Conflict could not be dismissed.",
        ) from exc

    clear_cache()
    return ConflictFlagResponse.model_validate(conflict).model_copy(update={"severity": _severity(conflict)})


def _restore_vector_metadata(
    previous_vector_metadata: dict[int, dict[str, object]],
    document_ids: set[int],
) -> None:
    """Best-effort compensation after a partial Qdrant update.

    Quarantined documents (`is_current` was already `False` before this resolution
    attempt) are restored first and only unconditionally: if even that fails, the
    formerly-current documents are left quarantined rather than risk republishing them
    with metadata Qdrant never actually finished writing.
    """
    selected_ids = document_ids & previous_vector_metadata.keys()
    quarantined_ids = sorted(
        document_id for document_id in selected_ids if not bool(previous_vector_metadata[document_id]["is_current"])
    )
    active_ids = sorted(selected_ids - set(quarantined_ids))
    event = "conflict.resolve.vector_compensation_failed"

    quarantine_restored = True
    for document_id in quarantined_ids:
        try:
            restore_document_vector_metadata(document_id, previous_vector_metadata[document_id])
        except VectorStoreError as exc:
            quarantine_restored = False
            log_and_swallow_restore_failure(exc, document_id=document_id, event=event)

    if not quarantine_restored:
        return

    for document_id in active_ids:
        metadata = dict(previous_vector_metadata[document_id]) | {"is_current": True}
        try:
            restore_document_vector_metadata(document_id, metadata)
        except VectorStoreError as exc:
            log_and_swallow_restore_failure(exc, document_id=document_id, event=event)
