from datetime import datetime

from pydantic import BaseModel, Field

from backend.core.enums import DocumentRelationType


class DocumentRelationCreate(BaseModel):
    source_document_id: int
    target_document_id: int
    relation_type: DocumentRelationType
    scope_note: str | None = Field(default=None, max_length=5000)
    evidence: str | None = Field(default=None, max_length=5000)
    confidence: float | None = Field(default=None, ge=0, le=1)


class DocumentRelationReview(BaseModel):
    approve: bool


class DocumentRelationResponse(BaseModel):
    id: int
    source_document_id: int
    target_document_id: int
    relation_type: str
    scope_note: str | None = None
    evidence: str | None = None
    confidence: float | None = None
    review_status: str
    reviewed_by: int | None = None
    reviewed_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
