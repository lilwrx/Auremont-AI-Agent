"""Project catalogue — the list a Sale picks from when opening a consultation session.

`project_id` narrows two things when a session carries one: which project's stock the
inventory API is asked for, and which project's documents retrieval may read. Neither is
hard-blocked without it — a session with no project retrieves across the whole corpus and
resolves inventory through the INVENTORY_PROJECT_MAP catch-all.

Note these ids are *catalogue slugs* (`the-palma`, `vinhomes-ocean-park`), a different
namespace from the project codes the inventory API uses; `inventory_service` bridges them.

Reading (catalogue listing, category/zone detail, pricing tiers) is public — this is the
same marketing-grade project/pricing information a real showroom displays openly, and the
public homepage (frontend/src/routes/Landing.tsx, reached with no account) links straight
into these pages. Creating a project stays ADMIN-only; the document view-url endpoint stays
SALE/ADMIN-only since it is not visibility-filtered (see its own docstring below).
"""

import re
import unicodedata

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.deps import require_role
from backend.core.enums import UserRole
from backend.core.minio_client import presigned_get_url
from backend.core.mysql_client import get_db
from backend.models.project import Project
from backend.repositories.document import get_document
from backend.repositories.project import create_project, get_project, list_projects
from backend.schemas.project import (
    CategoryDetail,
    CategorySummary,
    CategoryTypeRow,
    ProjectCreate,
    ProjectDetail,
    ProjectResponse,
    ProjectSummary,
)

router = APIRouter(prefix="/projects", tags=["Projects"])


def _primary_type(details: dict | None) -> str:
    if not details:
        return "Dự án"
    categories = {p["category"] for p in (details.get("pricing") or []) if p.get("category")}
    if len(categories) > 1:
        return "Khu đô thị"
    return next(iter(categories), "Dự án")


def _price_from(details: dict | None) -> str | None:
    mins = [p["price_min"] for p in (details or {}).get("pricing") or [] if p.get("price_min") is not None]
    if not mins:
        return None
    return f"{min(mins) / 1_000_000_000:.1f} tỷ"


def _cover_image(details: dict | None) -> str | None:
    gallery = (details or {}).get("images", {}).get("gallery") or []
    return gallery[0] if gallery else None


def _to_summary(row: Project) -> ProjectSummary:
    return ProjectSummary(
        id=row.id,
        name=row.name,
        location=row.location,
        description=row.description,
        type=_primary_type(row.details),
        price_from=_price_from(row.details),
        cover_image=_cover_image(row.details),
    )


@router.get("", response_model=list[ProjectSummary])
def get_projects(db: Session = Depends(get_db)) -> list[ProjectSummary]:
    return [_to_summary(row) for row in list_projects(db) if row.details]


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def add_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> ProjectResponse:
    """Create a project. ADMIN only — this defines the catalogue Sales work against.

    Returns the flat `ProjectResponse` rather than `ProjectSummary`: a project is
    created without `details`, so the catalogue fields a summary derives from that
    column have nothing to read yet.
    """
    return create_project(db, payload)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project_detail(project_id: str, db: Session = Depends(get_db)) -> ProjectDetail:
    row = get_project(db, project_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    details: dict = row.details or {}
    project_info = details.get("project", {})
    summary = _to_summary(row)
    return ProjectDetail(
        **summary.model_dump(),
        developer=project_info.get("developer"),
        highlights=project_info.get("highlights", []),
        pricing=details.get("pricing", []),
        amenities=details.get("amenities", []),
        gallery=details.get("images", {}).get("gallery", []),
        contact=details.get("contact"),
    )


def _slugify(text: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()


def _billions(value: float) -> str:
    return f"{value / 1_000_000_000:.1f} tỷ"


CATEGORY_DESCRIPTION_FIELD = {
    "Chung cư": "apartment_description",
    "Biệt thự": "villa_description",
}


def _category_description(category: str, project_info: dict) -> str:
    field = CATEGORY_DESCRIPTION_FIELD.get(category)
    if field and project_info.get(field):
        return project_info[field]
    return project_info.get("overview_description") or project_info.get("description", "")


def _get_project_or_404(db: Session, project_id: str) -> Project:
    row = get_project(db, project_id)
    if row is None or not row.details:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


def _group_pricing_by_category(details: dict) -> dict[str, list[dict]]:
    """Preserves the order categories first appear in `pricing`."""
    groups: dict[str, list[dict]] = {}
    for tier in details.get("pricing", []):
        groups.setdefault(tier["category"], []).append(tier)
    return groups


_SHOPHOUSE_IMAGE_KEYWORDS = ("shop-thuong-mai", "shophouse", "shop")


def _cover_image_for(category: str, groups: dict[str, list[dict]], gallery: list[str]) -> str | None:
    if category == "Shophouse":
        for url in gallery:
            if any(keyword in url.lower() for keyword in _SHOPHOUSE_IMAGE_KEYWORDS):
                return url
        return None
    if not gallery:
        return None
    index = list(groups.keys()).index(category)
    return gallery[index % len(gallery)]


@router.get("/{project_id}/categories", response_model=list[CategorySummary])
def get_categories(project_id: str, db: Session = Depends(get_db)) -> list[CategorySummary]:
    row = _get_project_or_404(db, project_id)
    details: dict = row.details or {}
    gallery = details.get("images", {}).get("gallery", [])
    groups = _group_pricing_by_category(details)

    summaries = []
    for category, tiers in groups.items():
        mins = [t["price_min"] for t in tiers if t.get("price_min") is not None]
        maxs = [t["price_max"] for t in tiers if t.get("price_max") is not None]
        sizes_min = [t["size_min_sqm"] for t in tiers if t.get("size_min_sqm") is not None]
        sizes_max = [t["size_max_sqm"] for t in tiers if t.get("size_max_sqm") is not None]
        summaries.append(
            CategorySummary(
                slug=_slugify(category),
                name=category,
                price_from=_billions(min(mins)) if mins else "Liên hệ",
                price_to=_billions(max(maxs)) if maxs else "Liên hệ",
                size_from=min(sizes_min) if sizes_min else None,
                size_to=max(sizes_max) if sizes_max else None,
                types_count=len(tiers),
                cover_image=_cover_image_for(category, groups, gallery),
                type_names=[t["apartment_type"] for t in tiers],
            )
        )
    return summaries


@router.get("/{project_id}/categories/{category_slug}", response_model=CategoryDetail)
def get_category_detail(project_id: str, category_slug: str, db: Session = Depends(get_db)) -> CategoryDetail:
    row = _get_project_or_404(db, project_id)
    details: dict = row.details or {}
    project_info = details.get("project", {})
    gallery = details.get("images", {}).get("gallery", [])
    groups = _group_pricing_by_category(details)

    tiers = [t for t in details.get("pricing", []) if _slugify(t["category"]) == category_slug]
    if not tiers:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")

    category_name = tiers[0]["category"]
    types = [
        CategoryTypeRow(
            type=t["apartment_type"],
            size_range=(
                f"{t['size_min_sqm']} - {t['size_max_sqm']} m²"
                if t.get("size_min_sqm") is not None and t.get("size_max_sqm") is not None
                else "—"
            ),
            price_range=(
                f"{_billions(t['price_min'])} - {_billions(t['price_max'])}"
                if t.get("price_min") is not None and t.get("price_max") is not None
                else "Liên hệ"
            ),
            description=t.get("description"),
            storeys=t.get("storeys"),
        )
        for t in tiers
    ]

    return CategoryDetail(
        slug=category_slug,
        name=category_name,
        description=_category_description(category_name, project_info),
        cover_image=_cover_image_for(category_name, groups, gallery),
        types=types,
        amenities=details.get("amenities", []),
        highlights=project_info.get("highlights", []),
        gallery=gallery,
    )


@router.get(
    "/documents/{document_id}/view-url",
    dependencies=[Depends(require_role(UserRole.SALE, UserRole.ADMIN))],
)
def get_document_view_url(document_id: int, db: Session = Depends(get_db)) -> dict:
    """Temporary signed link so a Sale can open a cited document from the chat, not just
    Admin — the citation chip needs somewhere to point. Bucket stays private; the link
    itself expires after a few minutes.

    SALE/ADMIN only, explicitly (this used to ride on a router-level dependency that also
    covered the now-public catalogue endpoints above): it returns a signed link for ANY
    document id with no visibility filtering, so opening it to CUSTOMER/anonymous would let
    someone enumerate document ids and download INTERNAL-tier files directly, bypassing the
    PUBLIC-only clearance the customer chat flow otherwise enforces.
    """
    document = get_document(db, document_id)
    if document is None or not document.file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document has no stored file yet.",
        )

    url = presigned_get_url(settings.minio_bucket_documents, document.file_path)
    return {"url": url}
