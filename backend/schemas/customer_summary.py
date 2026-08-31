from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class CustomerNeeds(BaseModel):
    purchase_purpose: str | None = None
    projects: list[str] = Field(default_factory=list)
    property_types: list[str] = Field(default_factory=list)
    unit_types: list[str] = Field(default_factory=list)
    budget_min: int | None = Field(default=None, ge=0, description="Ngân sách tối thiểu bằng VND")
    budget_max: int | None = Field(default=None, ge=0, description="Ngân sách tối đa bằng VND")
    area_min_m2: float | None = Field(default=None, ge=0)
    area_max_m2: float | None = Field(default=None, ge=0)
    preferred_floor: str | None = None
    preferred_view: str | None = None
    purchase_timeline: str | None = None

    @field_validator("projects", "property_types", "unit_types", mode="after")
    @classmethod
    def _limit_multi_value_needs(cls, values: list[str]) -> list[str]:
        return values[:10]


class ConsideredUnit(BaseModel):
    unit_code: str
    project_id: str | None = None
    customer_reaction: str | None = None
    last_mentioned_at: datetime | None = None
    inventory_recheck_required: bool = True
    evidence_message_ids: list[int] = Field(default_factory=list)

    @field_validator("evidence_message_ids", mode="after")
    @classmethod
    def _limit_evidence_message_ids(cls, values: list[int]) -> list[int]:
        return values[:10]


class SaleCommitment(BaseModel):
    content: str
    status: Literal["pending", "completed", "cancelled"] = "pending"
    evidence_message_ids: list[int] = Field(default_factory=list)

    @field_validator("evidence_message_ids", mode="after")
    @classmethod
    def _limit_evidence_message_ids(cls, values: list[int]) -> list[int]:
        return values[:10]


class SummaryEvidence(BaseModel):
    field: str
    message_ids: list[int] = Field(default_factory=list)
    source_role: Literal["customer", "sale", "agent"]

    @field_validator("message_ids", mode="after")
    @classmethod
    def _limit_message_ids(cls, values: list[int]) -> list[int]:
        return values[:10]


class CustomerSummaryMetadata(BaseModel):
    needs: CustomerNeeds = Field(default_factory=CustomerNeeds)
    considered_units: list[ConsideredUnit] = Field(default_factory=list)
    objections: list[str] = Field(default_factory=list)
    pending_questions: list[str] = Field(default_factory=list)
    commitments: list[SaleCommitment] = Field(default_factory=list)
    sentiment: str | None = None
    urgency: str | None = None
    next_best_actions: list[str] = Field(default_factory=list)
    evidence: list[SummaryEvidence] = Field(default_factory=list)

    @field_validator("considered_units", "objections", "pending_questions", "commitments", mode="after")
    @classmethod
    def _limit_twenty_item_sections(cls, values: list) -> list:
        return values[:20]

    @field_validator("next_best_actions", mode="after")
    @classmethod
    def _limit_next_best_actions(cls, values: list[str]) -> list[str]:
        return values[:10]

    @field_validator("evidence", mode="after")
    @classmethod
    def _limit_evidence(cls, values: list[SummaryEvidence]) -> list[SummaryEvidence]:
        return values[:50]


class CustomerSummarySnapshot(BaseModel):
    """Schema-constrained output produced by Gemini after applying one message batch."""

    summary_text: str
    metadata: CustomerSummaryMetadata


class CustomerConversationSummaryResponse(BaseModel):
    customer_id: int
    customer_label: str
    summary_text: str
    metadata: CustomerSummaryMetadata
    last_processed_message_id: int
    source_message_count: int
    newly_processed_message_count: int = 0
    generated_at: datetime
    schema_version: str
    model_name: str
    from_cache: bool = False
    is_stale: bool = False
