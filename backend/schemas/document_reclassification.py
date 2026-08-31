"""API contracts for the explicit, admin-reviewed legacy metadata backfill.

The preview response intentionally contains no source text.  Uploaded files may contain
customer or commercial data and the Admin only needs the proposed metadata to decide
whether to apply it.
"""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator


class ReclassificationPreviewRequest(BaseModel):
    """A deliberately bounded list of documents to send to the classifier."""

    document_ids: list[int] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def _document_ids_are_unique(self) -> Self:
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("document_ids must not contain duplicates")
        return self


class LegacyReclassificationCandidate(BaseModel):
    document_id: int
    title: str
    status: str
    category: str
    project_id: str | None = None
    classification_version: str | None = None
    classification_confidence: float | None = None


class MetadataChange(BaseModel):
    stored: Any = None
    suggested: Any = None


class ProjectCandidate(BaseModel):
    project_id: str
    project_name: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class ProjectResolution(BaseModel):
    stored_project_id: str | None = None
    llm_project_id: str | None = None
    recommended_project_id: str | None = None
    candidates: list[ProjectCandidate] = Field(default_factory=list)
    requires_confirmation: bool = True
    warning: str | None = None


class ReclassificationPreviewItem(BaseModel):
    document_id: int
    title: str
    status: str
    source_sha256: str | None = None
    suggestion: dict[str, Any] | None = None
    changes: dict[str, MetadataChange] = Field(default_factory=dict)
    project_resolution: ProjectResolution | None = None
    confirmation_token: str | None = None
    error: str | None = None


class ReclassificationPreviewResponse(BaseModel):
    items: list[ReclassificationPreviewItem]
    previewed: int
    failed: int


class ReclassificationApplyItem(BaseModel):
    confirmation_token: str = Field(min_length=20)
    project_action: Literal["keep", "assign", "clear"] = "keep"
    project_id: str | None = None

    @model_validator(mode="after")
    def _project_action_is_consistent(self) -> Self:
        if self.project_action == "assign" and not (self.project_id or "").strip():
            raise ValueError("project_id is required when project_action='assign'")
        if self.project_action != "assign" and self.project_id is not None:
            raise ValueError("project_id is only accepted when project_action='assign'")
        return self


class ReclassificationApplyRequest(BaseModel):
    """Apply only previews the Admin has explicitly inspected and confirmed."""

    confirmation: Literal["APPLY_LLM_RECLASSIFICATION"]
    items: list[ReclassificationApplyItem] = Field(min_length=1, max_length=20)


class ReclassificationApplyResult(BaseModel):
    document_id: int | None = None
    title: str | None = None
    status: str
    category: str | None = None
    project_id: str | None = None
    is_current: bool | None = None
    reindexed: bool = False
    conflict_ids: list[int] = Field(default_factory=list)
    duplicate_document_ids: list[int] = Field(default_factory=list)
    error: str | None = None


class ReclassificationApplyResponse(BaseModel):
    items: list[ReclassificationApplyResult]
    applied: int
    failed: int
