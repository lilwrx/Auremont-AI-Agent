from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.core.enums import ConflictStatus

ConflictDetectionMethod = Literal["rule", "llm", "hybrid"]


class ConflictResolveRequest(BaseModel):
    keep_document_id: int


class ConflictFlagResponse(BaseModel):
    id: int
    document_id_a: int
    document_id_b: int
    description: str | None = None
    detection_method: ConflictDetectionMethod = "rule"
    confidence: float | None = Field(default=None, ge=0, le=1)
    similarity_score: float | None = Field(default=None, ge=0, le=1)
    conflict_type: str | None = None
    severity: Literal["low", "medium", "high"] = "medium"
    evidence: dict[str, Any] | None = None
    analysis_version: str | None = None
    status: ConflictStatus
    created_at: datetime
    resolved_by: int | None = None
    resolved_at: datetime | None = None

    model_config = {"from_attributes": True}


class ConflictDocumentSummary(BaseModel):
    id: int
    title: str
    project_id: str | None = None
    version_label: str | None = None
    issued_date: date | None = None
    effective_date: date | None = None
    uploaded_at: datetime | None = None
    category: str
    visibility: str
    summary: str | None = None
    classification_reason: str | None = None


class ConflictDetailResponse(ConflictFlagResponse):
    project_id: str | None = None
    project_name: str | None = None
    document_a: ConflictDocumentSummary
    document_b: ConflictDocumentSummary
