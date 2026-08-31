import logging
import time
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.audit import log_event
from backend.core.config import settings
from backend.core.deps import require_role
from backend.core.enums import (
    DocumentCategory,
    DocumentReviewStatus,
    DocumentStatus,
    DocumentVisibility,
    LegalStatus,
    UserRole,
)
from backend.core.minio_client import presigned_get_url
from backend.core.mysql_client import get_db
from backend.models.document import Document
from backend.models.user import User
from backend.repositories.document import (
    create_document,
    delete_document,
    get_document,
    is_document_eligible_after_classification_approval,
    list_documents,
    list_documents_for_metadata_edit,
    update_document_classification,
    update_document_visibility,
)
from backend.repositories.project import get_project
from backend.schemas.document import (
    DocumentClassificationUpdate,
    DocumentCreate,
    DocumentResponse,
)
from backend.schemas.document_reclassification import (
    LegacyReclassificationCandidate,
    ReclassificationApplyRequest,
    ReclassificationApplyResponse,
    ReclassificationApplyResult,
    ReclassificationPreviewRequest,
    ReclassificationPreviewResponse,
)
from backend.services.cache_service import clear_cache
from backend.services.document_coverage_service import (
    document_matches_project_scope,
    project_scope_aliases,
)
from backend.services.ingestion_service import (
    AI_SERVICE_QUOTA_PUBLIC_MESSAGE,
    DocumentAIQuotaExceededError,
    DocumentIngestionError,
    PromptInjectionError,
    _conflict_scope_lock,
    ingest_uploaded_document,
    reclassify_document,
    reindex_document,
    sanitize_and_scan,
)
from backend.services.legacy_reclassification_service import (
    InvalidConfirmationTokenError,
    LegacyReclassificationError,
    apply_document_reclassification,
    list_reclassification_candidates,
    preview_document_reclassification,
)
from backend.services.project_metadata_service import ProjectCatalogEntry, classification_project_catalog
from backend.services.vector_store_service import (
    VectorStoreError,
    delete_document_vectors,
    document_vector_metadata_snapshot,
    log_and_swallow_restore_failure,
    restore_document_vector_metadata,
    sync_document_vector_metadata,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/documents",
    tags=["Documents (Admin)"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)

ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".docx"}
_AI_QUOTA_RETRY_AFTER_SECONDS = 60

_MAGIC_BYTES = {
    ".pdf": (b"%PDF-",),
    ".docx": (b"PK", b"PK", b"PK"),
}


def _content_matches_extension(suffix: str, file_bytes: bytes) -> bool:
    signatures = _MAGIC_BYTES.get(suffix)
    if not signatures:
        return False
    return any(file_bytes.startswith(signature) for signature in signatures)


def _ai_quota_http_exception() -> HTTPException:
    """Translate provider quota exhaustion without exposing provider response details."""

    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=AI_SERVICE_QUOTA_PUBLIC_MESSAGE,
        headers={"Retry-After": str(_AI_QUOTA_RETRY_AFTER_SECONDS)},
    )


def _validate_project_id(db: Session, project_id: str | None) -> str | None:
    """Reject a stale/invented project selection before creating a document row."""

    normalised_project_id = project_id.strip() if project_id else None
    if normalised_project_id and get_project(db, normalised_project_id) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"project_id '{normalised_project_id}' does not exist in the project catalogue.",
        )
    return normalised_project_id


class IngestRequest(BaseModel):
    """Legacy raw-text endpoint; kept so the older flow does not break."""

    title: str
    raw_text: str
    file_path: str | None = None
    project_id: str | None = None


class IngestResponse(BaseModel):
    document_id: int
    status: str
    message: str


class VisibilityUpdateRequest(BaseModel):
    visibility: DocumentVisibility


class ReclassifyRequest(DocumentClassificationUpdate):
    """A complete Admin correction that may change retrieval/conflict scope safely.

    Category comes from ``DocumentClassificationUpdate`` and remains required. Project
    is deliberately available only on this controlled quarantine/rescan endpoint, never
    on the ordinary metadata PATCH.
    """

    project_id: str | None = None


class ProjectCatalogItem(BaseModel):
    id: str
    name: str
    location: str | None = None


@router.get("/project-catalog", response_model=list[ProjectCatalogItem])
def get_document_project_catalog(db: Session = Depends(get_db)) -> list[ProjectCatalogEntry]:
    """Complete live catalogue used by both LLM resolution and Admin correction.

    The public ``/projects`` catalogue intentionally hides rows without marketing
    details. Those rows are still valid document foreign keys, so the review UI needs
    this Admin-only list to avoid presenting a narrower choice set than the classifier.
    """

    return classification_project_catalog(db)


@router.get(
    "/llm-reclassification/candidates",
    response_model=list[LegacyReclassificationCandidate],
)
def get_llm_reclassification_candidates(
    legacy_only: bool = Query(default=True),
    pending_only: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[LegacyReclassificationCandidate]:
    """List stored originals that an Admin may explicitly preview.

    This endpoint is read-only and never calls the LLM. ``legacy_only=true`` selects
    rows whose persisted classifier version is null, rather than guessing from prose in
    the old classification reason. ``pending_only=true`` selects only completed
    documents whose metadata has not yet been approved by an Admin.
    """

    return list_reclassification_candidates(
        db,
        legacy_only=legacy_only,
        pending_only=pending_only,
        limit=limit,
    )


@router.post(
    "/llm-reclassification/preview",
    response_model=ReclassificationPreviewResponse,
)
def preview_llm_reclassification(
    payload: ReclassificationPreviewRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> ReclassificationPreviewResponse:
    """Run the current LLM on stored originals without changing MySQL or Qdrant."""

    started = time.perf_counter()
    items = [
        preview_document_reclassification(db, document_id=document_id, admin_id=admin.id)
        for document_id in payload.document_ids
    ]
    failed = sum(item.error is not None for item in items)
    log_event(
        "document.legacy_reclassification.preview",
        admin_id=admin.id,
        requested=len(payload.document_ids),
        previewed=len(items) - failed,
        failed=failed,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return ReclassificationPreviewResponse(items=items, previewed=len(items) - failed, failed=failed)


@router.post(
    "/llm-reclassification/apply",
    response_model=ReclassificationApplyResponse,
)
def apply_llm_reclassification(
    payload: ReclassificationApplyRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> ReclassificationApplyResponse:
    """Apply only short-lived signed previews explicitly confirmed by an Admin."""

    started = time.perf_counter()
    results: list[ReclassificationApplyResult] = []
    for item in payload.items:
        _clear_answer_cache()
        try:
            result = apply_document_reclassification(db, item=item, admin_id=admin.id)
        except (InvalidConfirmationTokenError, LegacyReclassificationError, DocumentIngestionError) as exc:
            db.rollback()
            result = ReclassificationApplyResult(status="failed", error=str(exc))
        except Exception:
            db.rollback()
            logger.exception(
                "Unexpected failure applying a legacy reclassification preview.",
                extra={"event": "document.legacy_reclassification.unexpected_apply_failure", "admin_id": admin.id},
            )
            result = ReclassificationApplyResult(
                status="failed",
                error="Could not apply the reclassification. The document remains quarantined; check server logs.",
            )
        results.append(result)

    failed = sum(item.error is not None for item in results)
    applied = len(results) - failed
    _clear_answer_cache()
    log_event(
        "document.legacy_reclassification.apply",
        admin_id=admin.id,
        requested=len(payload.items),
        applied=applied,
        failed=failed,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return ReclassificationApplyResponse(items=results, applied=applied, failed=failed)


@router.post(
    "/upload",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    file: UploadFile = File(...),
    project_id: str | None = Form(default=None),
    visibility: DocumentVisibility = Form(
        default=DocumentVisibility.INTERNAL,
    ),
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> IngestResponse:
    """Upload PDF/DOCX and defer indexing whenever classification needs review."""
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File name is required.",
        )

    suffix = Path(file.filename).suffix.lower()

    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Only PDF and DOCX files are supported.",
        )

    file_bytes = await file.read()

    if not file_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )

    if not _content_matches_extension(suffix, file_bytes):
        log_event(
            "document.upload.rejected",
            filename=file.filename,
            reason="content_does_not_match_extension",
            content_type=file.content_type,
            admin_id=admin.id,
        )
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="File content does not match its extension.",
        )

    if len(file_bytes) > settings.upload_max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(f"File exceeds the maximum allowed size of {settings.upload_max_bytes} bytes."),
        )

    project_id = _validate_project_id(db, project_id)

    document = create_document(
        db,
        DocumentCreate(
            title=file.filename,
            project_id=project_id,
            visibility=visibility,
        ),
        uploaded_by=admin.id,
    )

    log_event(
        "document.upload",
        document_id=document.id,
        filename=file.filename,
        size_bytes=len(file_bytes),
        content_type=file.content_type,
        project_id=project_id,
        visibility=visibility,
        admin_id=admin.id,
    )

    started = time.perf_counter()
    try:
        document = ingest_uploaded_document(
            db,
            document=document,
            filename=file.filename,
            file_bytes=file_bytes,
            content_type=file.content_type,
        )
    except PromptInjectionError as exc:
        log_event(
            "document.ingest.blocked",
            document_id=document.id,
            status=DocumentStatus.BLOCKED,
            reason="prompt_injection",
            finding_rule_ids=[finding.rule_id for finding in exc.findings],
            finding_pages=sorted({finding.page for finding in exc.findings if finding.page is not None}),
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return IngestResponse(
            document_id=document.id,
            status=DocumentStatus.BLOCKED,
            message="Tài liệu bị chặn vì phát hiện chỉ thị có nguy cơ điều khiển AI.",
        )
    except DocumentAIQuotaExceededError as exc:
        log_event(
            "document.ingest.failure",
            document_id=document.id,
            status=DocumentStatus.FAILED,
            reason="ai_quota_exhausted",
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise _ai_quota_http_exception() from exc
    except DocumentIngestionError as exc:
        log_event(
            "document.ingest.failure",
            document_id=document.id,
            status=DocumentStatus.FAILED,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Document ingestion failed. Check server logs.",
        ) from exc
    finally:
        await file.close()

    duplicate_quarantined = document.status == DocumentStatus.BLOCKED
    log_event(
        "document.ingest.duplicate_quarantined" if duplicate_quarantined else "document.ingest.success",
        document_id=document.id,
        status=document.status,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return IngestResponse(
        document_id=document.id,
        status=document.status,
        message=(
            "Document was quarantined because identical content already exists."
            if duplicate_quarantined
            else (
                "Document was classified and stored, but will only be chunked and indexed after Admin approval."
                if document.review_status != DocumentReviewStatus.APPROVED
                else "Document uploaded and indexed successfully."
            )
        ),
    )


@router.post(
    "/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ingest_document(
    payload: IngestRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> IngestResponse:
    """Legacy raw-text ingest endpoint."""
    try:
        sanitize_and_scan(payload.raw_text)
    except PromptInjectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Chặn file: phát hiện rủi ro",
        ) from exc

    project_id = _validate_project_id(db, payload.project_id)

    document = create_document(
        db,
        DocumentCreate(
            title=payload.title,
            file_path=payload.file_path,
            project_id=project_id,
        ),
        uploaded_by=admin.id,
    )

    return IngestResponse(
        document_id=document.id,
        status=document.status,
        message=f"Document '{document.title}' created successfully.",
    )


@router.post("/{document_id}/reindex", response_model=IngestResponse)
async def reindex_document_endpoint(
    document_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> IngestResponse:
    """Re-embed a stored document and rewrite its vectors, from the original file.

    Needed after a change to how vectors are built — enabling hybrid retrieval added a
    BM25 vector to every point, and documents ingested before that carry only a dense
    one. Run this over each document, then switch HYBRID_SEARCH_ENABLED on.
    """
    started = time.perf_counter()
    try:
        document = reindex_document(db, document_id=document_id)
    except DocumentAIQuotaExceededError as exc:
        log_event(
            "document.reindex.failure",
            document_id=document_id,
            admin_id=admin.id,
            reason="ai_quota_exhausted",
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise _ai_quota_http_exception() from exc
    except DocumentIngestionError as exc:
        log_event(
            "document.reindex.failure",
            document_id=document_id,
            admin_id=admin.id,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Could not re-index document {document_id}. Check server logs.",
        ) from exc

    log_event(
        "document.reindex.success",
        document_id=document.id,
        admin_id=admin.id,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    return IngestResponse(
        document_id=document.id,
        status=document.status,
        message="Document re-indexed successfully.",
    )


@router.post("/{document_id}/reclassify", response_model=DocumentResponse)
async def reclassify_document_endpoint(
    document_id: int,
    payload: ReclassifyRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> Document:
    """Correct category/project/scope under quarantine, then re-scan conflicts.

    The classification-review endpoint deliberately refuses category changes, since the
    category decides how the file is chunked and how conflicts are compared. This is the
    controlled path that does that work — previously the only way to fix a misclassified
    document was to delete it, rename the file and upload it again.
    """
    started = time.perf_counter()
    updates = payload.model_dump(exclude_unset=True)
    category = updates.pop("category")
    if "project_id" in updates:
        updates["project_id"] = _validate_project_id(db, updates.get("project_id"))
    _clear_answer_cache()
    try:
        document = reclassify_document(
            db,
            document_id=document_id,
            category=category,
            reviewed_by=admin.id,
            metadata_updates=updates or None,
        )
    except DocumentAIQuotaExceededError as exc:
        log_event(
            "document.reclassify.failure",
            document_id=document_id,
            to_category=category,
            to_project_id=updates.get("project_id"),
            admin_id=admin.id,
            reason="ai_quota_exhausted",
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise _ai_quota_http_exception() from exc
    except DocumentIngestionError as exc:
        log_event(
            "document.reclassify.failure",
            document_id=document_id,
            to_category=category,
            to_project_id=updates.get("project_id"),
            admin_id=admin.id,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    log_event(
        "document.reclassify.success",
        document_id=document.id,
        to_category=category,
        to_project_id=document.project_id,
        is_current=document.is_current,
        admin_id=admin.id,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    _clear_answer_cache()
    return document


@router.get("", response_model=list[DocumentResponse])
async def get_documents(
    coverage_scope: str | None = Query(default=None, min_length=1),
    db: Session = Depends(get_db),
) -> list[Document]:
    documents = list_documents(db)
    if coverage_scope is None:
        return documents

    project = get_project(db, coverage_scope)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Coverage project not found.",
        )
    aliases = project_scope_aliases(project)
    return [document for document in documents if document_matches_project_scope(document, project, aliases)]


@router.get("/{document_id}/view-url")
async def get_document_view_url(
    document_id: int,
    db: Session = Depends(get_db),
) -> dict:
    """Temporary signed link (expires after a few minutes) to view the original file —
    the document bucket is private, so the object key cannot be linked to directly."""
    document = get_document(db, document_id)
    if document is None or not document.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document has no stored file yet.",
        )

    url = presigned_get_url(settings.minio_bucket_documents, document.file_path)
    return {"url": url}


@router.patch(
    "/{document_id}/visibility",
    response_model=DocumentResponse,
)
async def set_document_visibility(
    document_id: int,
    payload: VisibilityUpdateRequest,
    db: Session = Depends(get_db),
) -> DocumentResponse:
    document = get_document(db, document_id, for_update=True)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id={document_id} not found.",
        )
    if document.status != DocumentStatus.COMPLETED:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document visibility can change only after ingestion completes (status={document.status}).",
        )
    if document.visibility == payload.visibility:
        db.commit()
        db.refresh(document)
        return document

    previous_metadata = document_vector_metadata_snapshot(document)
    loosening_access = (
        document.visibility == DocumentVisibility.INTERNAL and payload.visibility == DocumentVisibility.PUBLIC
    )

    if loosening_access:
        quarantine_attempted = False
        try:
            quarantine_attempted = True
            sync_document_vector_metadata(document, is_current=False)
            update_document_visibility(db, document_id, payload.visibility, commit=False)
            db.commit()
        except (VectorStoreError, SQLAlchemyError, ValueError) as exc:
            try:
                if quarantine_attempted:
                    try:
                        restore_document_vector_metadata(document.id, previous_metadata)
                    except VectorStoreError as restore_exc:
                        log_and_swallow_restore_failure(
                            restore_exc,
                            document_id=document.id,
                            event="document.visibility.vector_compensation_failed",
                        )
            finally:
                db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Document visibility was not changed because retrieval could not be safely quarantined.",
            ) from exc

        try:
            document = get_document(db, document_id, for_update=True)
            if document is None:  # pragma: no cover - deletion also needs the same row lock
                raise ValueError(f"Document with id={document_id} not found.")
            sync_document_vector_metadata(document, is_current=_safe_vector_current(document))
            db.commit()
            db.refresh(document)
            _clear_answer_cache()
            return document
        except (VectorStoreError, SQLAlchemyError, ValueError) as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Visibility changed in MySQL, but retrieval remains quarantined until synchronisation is retried.",
            ) from exc

    try:
        document = update_document_visibility(
            db,
            document_id,
            payload.visibility,
            commit=False,
        )
        sync_document_vector_metadata(document, is_current=_safe_vector_current(document))
        db.commit()
        db.refresh(document)
        _clear_answer_cache()
        return document
    except (VectorStoreError, SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document visibility was not fully synchronised; retrieval remains on the more restrictive value.",
        ) from exc


@router.delete(
    "/{document_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_document(
    document_id: int,
    db: Session = Depends(get_db),
) -> None:
    """Delete a document from the knowledge base, vectors included.

    Vectors go first, on purpose. Qdrant is what retrieval actually reads, so a row
    deleted from MySQL while its chunks survive means the Agent keeps quoting a price
    list the Admin believes is gone — and cites a `document_id` that no longer resolves.
    Dropping the vectors first makes the failure mode retryable instead: the row stays,
    the Admin sees the document still listed and can press delete again.
    """
    if get_document(db, document_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id={document_id} not found.",
        )

    try:
        delete_document_vectors(document_id)
    except VectorStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not remove the document's vectors; nothing was deleted. Try again.",
        ) from exc

    try:
        delete_document(db, document_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    _clear_answer_cache()


@router.get(
    "/metadata-editable",
    response_model=list[DocumentResponse],
)
async def get_documents_for_metadata_edit(
    db: Session = Depends(get_db),
) -> list[Document]:
    """Ingested documents whose metadata an Admin can still correct.

    Includes the pending-review queue as well as previously approved documents whose
    metadata an Admin may need to correct later.
    """

    return list_documents_for_metadata_edit(db)


@router.patch(
    "/{document_id}/classification",
    response_model=DocumentResponse,
)
async def update_document_metadata(
    document_id: int,
    payload: DocumentClassificationUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> DocumentResponse:
    """Correct a document's metadata after ingestion.

    For a pending LLM suggestion this is the approval step. For an approved document it is
    a metadata correction. `legal_status` remains load-bearing: setting it to
    expired/repealed takes the document out of retrieval.
    """

    existing = get_document(db, document_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document with id={document_id} not found.",
        )

    if existing.review_status == DocumentReviewStatus.PENDING:
        updates = payload.model_dump(exclude_unset=True)
        category = updates.pop("category")
        started = time.perf_counter()
        try:
            document = reclassify_document(
                db,
                document_id=document_id,
                category=category,
                reviewed_by=admin.id,
                metadata_updates=updates,
            )
        except DocumentAIQuotaExceededError as exc:
            log_event(
                "document.classification.approval_failure",
                document_id=document_id,
                admin_id=admin.id,
                reason="ai_quota_exhausted",
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            raise _ai_quota_http_exception() from exc
        except DocumentIngestionError as exc:
            log_event(
                "document.classification.approval_failure",
                document_id=document_id,
                admin_id=admin.id,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            validation_markers = (
                "cannot be approved for AI retrieval",
                "no stored original file",
                "does not exist in the project catalogue",
                "not ready",
                "changed while",
                "was reviewed while",
            )
            error_status = (
                status.HTTP_409_CONFLICT
                if any(marker in str(exc) for marker in validation_markers)
                else status.HTTP_503_SERVICE_UNAVAILABLE
            )
            raise HTTPException(status_code=error_status, detail=str(exc)) from exc

        log_event(
            "document.classification.approved_and_indexed",
            document_id=document.id,
            admin_id=admin.id,
            category=document.category,
            is_current=document.is_current,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        _clear_answer_cache()
        return document

    try:
        existing = get_document(db, document_id, for_update=True)
        if existing is None:
            raise ValueError(f"Document with id={document_id} not found.")
        was_pending_review = existing.review_status == DocumentReviewStatus.PENDING
        document = update_document_classification(
            db,
            document_id=document_id,
            payload=payload,
            reviewed_by=admin.id,
            commit=False,
        )
        sync_document_vector_metadata(document, is_current=False)
        db.commit()
    except ValueError as exc:
        db.rollback()
        if any(
            marker in str(exc)
            for marker in (
                "already been reviewed",
                "not ready for classification review",
                "requires quarantine, conflict rescan and controlled re-indexing",
                "requires a controlled conflict rescan",
            )
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except (VectorStoreError, SQLAlchemyError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document classification was not approved because retrieval metadata could not be synchronised.",
        ) from exc

    try:
        with _conflict_scope_lock(db, document):
            refreshed = get_document(db, document_id, for_update=True)
            if refreshed is None:  # pragma: no cover - deletion also requires the row lock
                raise ValueError(f"Document with id={document_id} not found.")
            document = refreshed
            if was_pending_review:
                document.is_current = is_document_eligible_after_classification_approval(db, document)

            db.commit()
            refreshed = get_document(db, document_id, for_update=True)
            if refreshed is None:  # pragma: no cover - deletion also requires this row lock
                raise ValueError(f"Document with id={document_id} not found.")
            document = refreshed
            publication_current = bool(
                _safe_vector_current(document) and is_document_eligible_after_classification_approval(db, document)
            )
            if document.is_current != publication_current:
                document.is_current = publication_current
                db.flush()
            sync_document_vector_metadata(document, is_current=publication_current)
            db.commit()
        _clear_answer_cache()
        return document
    except (DocumentIngestionError, VectorStoreError, SQLAlchemyError, ValueError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Document was approved in MySQL, but retrieval remains quarantined until synchronisation is retried.",
        ) from exc


def _clear_answer_cache() -> None:
    """Drop every cached answer after the document set behind them changes.

    A question answered (and cached) before the change keeps serving that stale answer
    forever otherwise — quoting a document that has since been deleted, retired by a
    conflict, reclassified, or made public/internal. The cache is keyed by question
    similarity and has no way to know which entries touched THIS document, so the only
    correct move is clearing all of it.

    Best-effort: a failure here never blocks the change that triggered it (see
    clear_cache's own fail-silent contract).
    """
    clear_cache()


def _safe_vector_current(document: Document) -> bool:
    """Clamp cross-store publication to states retrieval is allowed to expose."""
    return bool(
        document.is_current
        and document.status == DocumentStatus.COMPLETED
        and document.review_status == DocumentReviewStatus.APPROVED
        and document.category != DocumentCategory.OTHER
        and document.legal_status
        not in {
            LegalStatus.NOT_YET_EFFECTIVE,
            LegalStatus.EXPIRED,
            LegalStatus.REPEALED,
            LegalStatus.REPLACED,
        }
    )
