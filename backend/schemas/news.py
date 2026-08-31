from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NewsTopic = Literal[
    "official_update",
    "project_progress",
    "infrastructure",
    "market_potential",
    "promotion",
]
NewsStatus = Literal[
    "draft",
    "pending_review",
    "changes_requested",
    "rejected",
    "published",
    "archived",
]


class _NewsFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=5, max_length=500)
    summary: str | None = Field(default=None, max_length=2000)
    content: str = Field(min_length=50, max_length=50_000)
    image_url: str | None = Field(default=None, max_length=3000)
    topic: NewsTopic = "official_update"
    project_names: list[str] = Field(default_factory=list, max_length=12)

    @field_validator("title", "summary", "content", mode="before")
    @classmethod
    def normalize_text(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        if value.strip() == "":
            return None
        return value.strip()

    @field_validator("image_url", mode="before")
    @classmethod
    def validate_optional_url(cls, value: object) -> object:
        if value is None or value == "":
            return None
        if not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized.lower().startswith(("http://", "https://")):
            raise ValueError("URL must use http or https")
        return normalized

    @field_validator("project_names", mode="after")
    @classmethod
    def unique_projects(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = " ".join(raw.split())[:150]
            key = value.casefold()
            if value and key not in seen:
                result.append(value)
                seen.add(key)
        return result


class NewsDraftCreate(_NewsFields):
    pass


class NewsDraftUpdate(_NewsFields):
    pass


class NewsReviewRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        return value.strip() or None


class NewsReviewRequiredRequest(BaseModel):
    note: str = Field(min_length=3, max_length=2000)

    @field_validator("note", mode="before")
    @classmethod
    def normalize_note(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class NewsArticleResponse(BaseModel):
    id: int
    canonical_url: str
    source_id: str
    source_name: str
    title: str
    summary: str | None
    content: str | None
    image_url: str | None
    topic: str
    project_names: list[str]
    published_at: datetime | None
    fetched_at: datetime

    model_config = {"from_attributes": True}


class NewsWorkflowArticleResponse(NewsArticleResponse):
    status: NewsStatus
    author_id: int | None
    author_name: str
    reviewer_id: int | None
    reviewer_name: str | None
    review_note: str | None
    submitted_at: datetime | None
    reviewed_at: datetime | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class NewsListResponse(BaseModel):
    items: list[NewsArticleResponse]
    total: int
    offset: int
    limit: int


class NewsWorkflowListResponse(BaseModel):
    items: list[NewsWorkflowArticleResponse]
    total: int
    offset: int
    limit: int


class NewsImageUploadResponse(BaseModel):
    image_url: str
