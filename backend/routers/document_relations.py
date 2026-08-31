import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.core.deps import require_role
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.models.document_relation import DocumentRelation
from backend.models.user import User
from backend.repositories.document_relation import (
    create_document_relation,
    list_document_relations,
    review_document_relation,
)
from backend.schemas.document_relation import (
    DocumentRelationCreate,
    DocumentRelationResponse,
    DocumentRelationReview,
)
from backend.services.vector_store_service import (
    VectorStoreError,
    log_and_swallow_restore_failure,
    restore_document_vector_metadata,
    sync_document_vector_metadata,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/document-relations",
    tags=["Document Relations (Admin)"],
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)


@router.get("", response_model=list[DocumentRelationResponse])
async def get_document_relations(
    pending_only: bool = False,
    db: Session = Depends(get_db),
) -> list[DocumentRelation]:
    return list_document_relations(db, pending_only=pending_only)


@router.post("", response_model=DocumentRelationResponse, status_code=status.HTTP_201_CREATED)
async def add_document_relation(
    payload: DocumentRelationCreate,
    db: Session = Depends(get_db),
) -> DocumentRelationResponse:
    try:
        return create_document_relation(db, payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{relation_id}/review", response_model=DocumentRelationResponse)
async def review_relation(
    relation_id: int,
    payload: DocumentRelationReview,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> DocumentRelationResponse:
    attempted_document_id: int | None = None
    previous_vector_metadata: dict[str, object] | None = None
    try:
        relation, superseded, previous_vector_metadata = review_document_relation(
            db,
            relation_id,
            approve=payload.approve,
            reviewed_by=admin.id,
            commit=False,
        )
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Relation review could not be prepared.",
        ) from exc

    if superseded is not None:
        attempted_document_id = superseded.id
        try:
            sync_document_vector_metadata(superseded, is_current=False)
        except VectorStoreError as exc:
            try:
                if previous_vector_metadata is not None:
                    try:
                        restore_document_vector_metadata(attempted_document_id, previous_vector_metadata)
                    except VectorStoreError as restore_exc:
                        log_and_swallow_restore_failure(
                            restore_exc,
                            document_id=attempted_document_id,
                            event="document_relation.vector_compensation_failed",
                        )
            finally:
                db.rollback()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Relation was not reviewed because retrieval metadata could not be synchronised.",
            ) from exc

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The relation target remains quarantined because the MySQL commit outcome could not be confirmed.",
        ) from exc

    db.refresh(relation)
    return relation
