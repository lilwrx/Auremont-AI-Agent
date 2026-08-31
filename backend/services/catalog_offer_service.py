"""Structured catalogue search across every project and product type.

The inventory API answers a different question from the project catalogue. Inventory is
the source of truth for a concrete unit and its current status; ``Project.details.pricing``
contains published/reference ranges for apartment, villa and shop product types. Keeping
the two sources separate prevents a catalogue range from being presented as a currently
available unit while still allowing broad questions ("căn dưới 3 tỷ", "biệt thự Hải Âu")
to be answered when the live API does not cover that catalogue project.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.models.project import Project
from backend.services import inventory_service, search_criteria

MAX_CATALOG_OFFERS = 24


@dataclass(frozen=True)
class CatalogOffer:
    project_id: str
    project_name: str
    sub_zone: str | None
    category: str
    unit_type: str
    area_min_m2: float | None
    area_max_m2: float | None
    price_min: float | None
    price_max: float | None
    storeys: str | None = None
    description: str | None = None
    price_note: str | None = None


def search_offers(
    db: Session | None,
    query: str,
    *,
    project_ids: Iterable[str] | None = None,
    excluded_project_ids: Iterable[str] | None = None,
    criteria: search_criteria.SearchCriteria | None = None,
    limit: int = MAX_CATALOG_OFFERS,
) -> list[CatalogOffer]:
    """Return catalogue price tiers intersecting the requested hard constraints.

    Range matching uses intersection, not full containment. A published 2.4–3.3 billion
    tier is relevant to "under 3 billion" because part of the tier may fit; the formatter
    labels the whole range as reference data so the answer cannot imply every unit in the
    tier meets the ceiling.
    """
    if db is None or limit <= 0:
        return []

    active = criteria or search_criteria.merge_criteria(
        search_criteria.SearchCriteria(), search_criteria.parse_criteria(query)
    )
    scoped_ids = set(project_ids or [])
    excluded_ids = set(excluded_project_ids or [])
    include_children = bool(active.constraints)
    rows = db.query(Project).all()
    offers: list[CatalogOffer] = []

    for project in rows:
        if scoped_ids and not _project_is_in_scope(project, scoped_ids, include_children=include_children):
            continue
        if excluded_ids and _project_is_in_scope(project, excluded_ids):
            continue
        details = project.details or {}
        info = details.get("project") or {}
        pricing = details.get("pricing") or []

        categories = {tier["category"] for tier in pricing if isinstance(tier, dict) and tier.get("category")}
        if "Chung cư" in categories and len(categories) > 1 and project.id not in scoped_ids:
            continue

        for tier in pricing:
            if not isinstance(tier, dict):
                continue
            offer = _to_offer(project, info, tier)
            if _matches(offer, active):
                offers.append(offer)

    offers.sort(
        key=lambda item: (
            -_preference_score(item, active),
            item.price_min is None,
            item.price_min if item.price_min is not None else float("inf"),
            item.project_name.casefold(),
            item.unit_type.casefold(),
        )
    )
    return _diversify(offers, limit)


def format_offers(offers: list[CatalogOffer], criteria: search_criteria.SearchCriteria | None = None) -> str:
    """Grounding block shared by Generate and Verify."""
    if not offers:
        return ""
    lines = [
        "BẢNG GIÁ CATALOGUE THAM KHẢO (không phải xác nhận căn đang còn; trạng thái phải lấy từ tồn kho real-time):"
    ]
    for offer in offers:
        location = offer.project_name
        if offer.sub_zone and offer.sub_zone.casefold() not in location.casefold():
            location = f"{location} · {offer.sub_zone}"
        lines.append(
            f"- {location} | {offer.category} | {offer.unit_type} | "
            f"diện tích {_range_text(offer.area_min_m2, offer.area_max_m2, 'm²')} | "
            f"giá tham khảo {_price_range_text(offer.price_min, offer.price_max, offer.price_note)}"
            + (f" | {offer.storeys}" if offer.storeys else "")
        )
    lines.append(
        "Khi một khoảng giá chỉ giao với ngân sách khách, phải nói 'mức giá khởi điểm/phần dưới của khoảng có thể phù hợp' "
        "và đề nghị kiểm tra tồn kho; không được nói toàn bộ loại căn đều nằm trong ngân sách."
    )
    if criteria is not None:
        unsupported = [
            constraint.describe()
            for constraint in criteria.constraints
            if constraint.field
            in {
                search_criteria.FIELD_DIRECTIONS,
                search_criteria.FIELD_VIEWS,
                search_criteria.FIELD_TOWERS,
                search_criteria.FIELD_FLOORS,
            }
        ]
        unsupported.extend(criteria.required_features)
        unsupported.extend(criteria.preferred_features)
        if unsupported:
            lines.append(
                "ĐỘ PHỦ KHỚP MỘT PHẦN: catalogue chưa có trường cấp mã căn để xác nhận "
                + "; ".join(dict.fromkeys(unsupported))
                + ". Các dòng phía trên vẫn là ứng viên khớp những tiêu chí catalogue có dữ liệu. "
                "BẮT BUỘC nêu các ứng viên đó trước, rồi ghi rõ phần chưa xác nhận; không được kết luận "
                "không có lựa chọn chỉ vì một tiêu chí ưu tiên đang thiếu dữ liệu."
            )
    return "\n".join(lines)


def _preference_score(offer: CatalogOffer, criteria: search_criteria.SearchCriteria) -> float:
    """Rank supported soft constraints without discarding partial matches."""
    score = 0.0
    for constraint in criteria.constraints:
        if constraint.strength != search_criteria.Strength.SOFT:
            continue
        if constraint.field == search_criteria.FIELD_AREA:
            score += _range_fit_score(offer.area_min_m2, offer.area_max_m2, *constraint.value)
        elif constraint.field == search_criteria.FIELD_PRICE:
            score += _range_fit_score(offer.price_min, offer.price_max, *constraint.value)
    return score


def _range_fit_score(
    item_min: float | None,
    item_max: float | None,
    wanted_min: float,
    wanted_max: float,
) -> float:
    """Intersection-over-union rewards a close range over a merely broad overlap."""
    if item_min is None and item_max is None:
        return 0.0
    lower = item_min if item_min is not None else item_max
    upper = item_max if item_max is not None else item_min
    if lower is None or upper is None:
        raise ValueError("At least one catalogue range bound is required.")
    if lower == upper:
        return 1.0 if wanted_min <= lower <= wanted_max else 0.0
    if wanted_max == float("inf"):
        return 1.0 if upper >= wanted_min else 0.0
    intersection = max(0.0, min(upper, wanted_max) - max(lower, wanted_min))
    union = max(upper, wanted_max) - min(lower, wanted_min)
    if union == 0:
        return 1.0 if lower == wanted_min else 0.0
    return intersection / union


def build_catalog_overview(db: Session | None) -> str:
    """A complete, deterministic index of every project grouped by product category.

    Exists for "what do you have at all" survey questions ("có những dự án nào", "danh
    sách phân khu"), where RAG's top-k semantic retrieval is the wrong tool: it returns
    whichever ~8 chunks score closest to the question's own wording, an arbitrary subset
    that happens to skip whole categories (villas, shophouses) whenever no matching
    project document scores high enough to make the cut. This instead reads straight from
    every `Project` row, the same source `routers/projects.py::_primary_type` already
    trusts to classify a project's category from its own pricing tiers.
    """
    if db is None:
        return ""

    groups: dict[str, list[str]] = {}
    for project in db.query(Project).all():
        details = project.details or {}
        pricing = details.get("pricing") or []
        if not pricing:
            continue
        categories = {tier["category"] for tier in pricing if tier.get("category")}
        category = next(iter(categories)) if len(categories) == 1 else "Khu đô thị"
        name = project.name.split(" - ", 1)[0]
        groups.setdefault(category, []).append(name)

    if not groups:
        return ""

    lines = ["TỔNG QUAN DANH MỤC DỰ ÁN (đầy đủ, không phụ thuộc vào tài liệu được truy xuất):"]
    for category in sorted(groups):
        names = sorted(dict.fromkeys(groups[category]))
        lines.append(f"- {category}: {', '.join(names)}")
    return "\n".join(lines)


def _to_offer(project: Project, info: dict, tier: dict) -> CatalogOffer:
    unit_type = str(tier.get("apartment_type") or tier.get("type") or tier.get("category") or "Chưa phân loại")
    return CatalogOffer(
        project_id=project.id,
        project_name=str(info.get("name") or project.name or project.id),
        sub_zone=_string_or_none(info.get("sub_zone")),
        category=str(tier.get("category") or "Bất động sản"),
        unit_type=unit_type,
        area_min_m2=_number_or_none(tier.get("size_min_sqm")),
        area_max_m2=_number_or_none(tier.get("size_max_sqm")),
        price_min=_number_or_none(tier.get("price_min")),
        price_max=_number_or_none(tier.get("price_max")),
        storeys=_string_or_none(tier.get("storeys")),
        description=_string_or_none(tier.get("description")),
        price_note=_string_or_none(tier.get("price_note")),
    )


def _matches(offer: CatalogOffer, criteria: search_criteria.SearchCriteria) -> bool:
    type_constraints = [
        constraint for constraint in criteria.filtering() if constraint.field == search_criteria.FIELD_UNIT_TYPES
    ]
    if type_constraints:
        actual_candidates = inventory_service._extract_unit_types(f"{offer.unit_type} {offer.category}")
        if not actual_candidates:
            normalized_type = inventory_service._normalize_unit_type(offer.unit_type)
            actual_candidates = [normalized_type] if normalized_type else []
        for constraint in type_constraints:
            matches = any(
                inventory_service.unit_type_matches(actual, wanted)
                for actual in actual_candidates
                for wanted in constraint.value
            )
            if constraint.strength == search_criteria.Strength.EXCLUDED and matches:
                return False
            if constraint.strength != search_criteria.Strength.EXCLUDED and not matches:
                return False

    subdivision_constraints = [
        constraint for constraint in criteria.filtering() if constraint.field == search_criteria.FIELD_SUBDIVISIONS
    ]
    if subdivision_constraints:
        actual = {
            inventory_service._normalize_text(value).removeprefix("the ")
            for value in (offer.project_id.replace("-", " "), offer.project_name, offer.sub_zone)
            if value
        }
        for constraint in subdivision_constraints:
            wanted = {inventory_service._normalize_text(value).removeprefix("the ") for value in constraint.value}
            matches = bool(actual & wanted)
            if constraint.strength == search_criteria.Strength.EXCLUDED and matches:
                return False
            if constraint.strength != search_criteria.Strength.EXCLUDED and not matches:
                return False

    price = criteria.get(search_criteria.FIELD_PRICE)
    if price is not None and not _ranges_intersect(offer.price_min, offer.price_max, *price.value):
        return False

    area = criteria.get(search_criteria.FIELD_AREA)
    return not (
        area is not None
        and area.strength != search_criteria.Strength.SOFT
        and not _ranges_intersect(offer.area_min_m2, offer.area_max_m2, *area.value)
    )


def _project_is_in_scope(project: Project, scope_ids: set[str], *, include_children: bool = True) -> bool:
    """Match a project itself, and a direct catalogue child when children are in scope.

    `include_children` is False for a scoped search carrying NO unit constraints, i.e. the
    question named the project and nothing else ("gia o Vinhomes Ocean Park"). That asks
    about the scoped project's own tiers; expanding it buries them under every sub-zone's.
    A search that does filter for units ("duoi 4 ty", "2PN 60-70m2") means the opposite -
    the sub-zones are where those units actually live, so children must come along.
    """
    if project.id in scope_ids:
        return True
    if not include_children:
        return False
    info = (project.details or {}).get("project") or {}
    return info.get("parent_project_id") in scope_ids


def _ranges_intersect(
    item_min: float | None,
    item_max: float | None,
    wanted_min: float,
    wanted_max: float,
) -> bool:
    if item_min is None and item_max is None:
        return True
    lower = item_min if item_min is not None else item_max
    upper = item_max if item_max is not None else item_min
    if lower is None or upper is None:
        raise ValueError("At least one catalogue range bound is required.")
    return lower <= wanted_max and upper >= wanted_min


def _diversify(offers: list[CatalogOffer], limit: int) -> list[CatalogOffer]:
    """Round-robin projects so a broad result is not monopolised by one subdivision."""
    buckets: dict[str, list[CatalogOffer]] = {}
    for offer in offers:
        buckets.setdefault(offer.project_id, []).append(offer)
    result: list[CatalogOffer] = []
    while buckets and len(result) < limit:
        for project_id in list(buckets):
            result.append(buckets[project_id].pop(0))
            if not buckets[project_id]:
                del buckets[project_id]
            if len(result) >= limit:
                break
    return result


def _number_or_none(value) -> float | None:
    try:
        return float(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None


def _string_or_none(value) -> str | None:
    return str(value).strip() if value is not None and str(value).strip() else None


def _range_text(minimum: float | None, maximum: float | None, suffix: str) -> str:
    if minimum is None and maximum is None:
        return "chưa có"
    if minimum == maximum or maximum is None:
        return f"{minimum:g} {suffix}" if minimum is not None else f"{maximum:g} {suffix}"
    if minimum is None:
        return f"đến {maximum:g} {suffix}"
    return f"{minimum:g}–{maximum:g} {suffix}"


def _price_range_text(minimum: float | None, maximum: float | None, note: str | None) -> str:
    if minimum is None and maximum is None:
        return note or "chưa có trong catalogue"
    return _range_text(
        minimum / 1_000_000_000 if minimum is not None else None,
        maximum / 1_000_000_000 if maximum is not None else None,
        "tỷ đồng",
    )
