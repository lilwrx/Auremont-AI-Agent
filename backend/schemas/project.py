from datetime import datetime

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    location: str | None = None
    description: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    location: str | None = None
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProjectSummary(BaseModel):
    """Condensed data for a project card on the project lookup page — derived from `Project.details`."""

    id: str
    name: str
    location: str | None = None
    description: str | None = None
    type: str
    price_from: str | None = None
    cover_image: str | None = None

    model_config = {"from_attributes": True}


class ProjectDetail(ProjectSummary):
    developer: str | None = None
    highlights: list[str] = []
    pricing: list[dict] = []
    amenities: list[dict] = []
    gallery: list[str] = []
    contact: dict | None = None


class CategorySummary(BaseModel):
    """Groups product types (Apartment/Villa/Shophouse) within a SINGLE project —
    used on the lookup page because this is an internal Sale tool for one large
    urban development, not a marketplace listing multiple different projects."""

    slug: str
    name: str
    price_from: str
    price_to: str
    size_from: float | None = None
    size_to: float | None = None
    types_count: int
    cover_image: str | None = None
    type_names: list[str] = []


class CategoryTypeRow(BaseModel):
    type: str
    size_range: str
    price_range: str
    description: str | None = None
    storeys: str | None = None


class CategoryDetail(BaseModel):
    slug: str
    name: str
    description: str
    cover_image: str | None = None
    types: list[CategoryTypeRow]
    amenities: list[dict] = []
    highlights: list[str] = []
    gallery: list[str] = []
