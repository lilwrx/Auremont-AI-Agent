"""Tool for looking up unit inventory through the company's real-time internal API.

The Main Agent calls this (Function Calling) when a Sale's question needs live inventory
data — something deliberately kept out of the Vector DB, because stock changes constantly
and anything ingested into Qdrant would answer with stale numbers.

During the build phase `INVENTORY_API_URL` points at a mock API (mockapi.io) shaped
exactly like the internal production API, so switching to the real one is an environment
variable change rather than a code change.

Every API failure is wrapped in `InventoryApiError` so the router/pipeline can show the
proper "Tạm thời không tra được tồn kho" message instead of letting the error escape as a 500.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass, fields

import httpx

from backend.core.config import settings
from backend.utils.text import sanitize_external_field
from backend.utils.vnd import BUDGET_UNIT_ALTERNATION_WITH_BARE_T, Profile, parse_vnd

logger = logging.getLogger(__name__)

INVENTORY_TIMEOUT_SECONDS = 5.0

_UNIT_TYPE_PATTERN = re.compile(
    r"\b("
    r"\d+\s*(?:pn|br|phòng\s*ngủ|phong\s*ngu|ngủ|ngu)(?:\s*\+\s*(?:1)?)?"
    r"|penthouse|studio|shophouse|duplex|officetel"
    r"|căn\s*hộ|can\s*ho|chung\s*cư|chung\s*cu"
    r"|biệt\s*thự\s*(?:đơn\s*lập|song\s*lập|liền\s*kề)?"
    r"|biet\s*thu\s*(?:don\s*lap|song\s*lap|lien\s*ke)?"
    r"|đơn\s*lập|don\s*lap|song\s*lập|song\s*lap"
    r"|nhà\s*phố\s*(?:thương\s*mại)?|nha\s*pho\s*(?:thuong\s*mai)?"
    r"|liền\s*kề|lien\s*ke|shop\s*thương\s*mại|shop\s*thuong\s*mai"
    r"|nhà\s*riêng|nha\s*rieng|nhà\s*(?:trong\s*)?(?:hẻm|ngõ)|nha\s*(?:trong\s*)?(?:hem|ngo)"
    r"|nhà\s*mặt\s*tiền|nha\s*mat\s*tien|nhà\s*cấp\s*4|nha\s*cap\s*4"
    r"|phòng\s*trọ|phong\s*tro|nhà\s*nguyên\s*căn|nha\s*nguyen\s*can"
    r"|đất\s*nền|dat\s*nen|đất\s*thổ\s*cư|dat\s*tho\s*cu|đất\s*dự\s*án|dat\s*du\s*an"
    r"|trang\s*trại|trang\s*trai|nhà\s*vườn|nha\s*vuon|kho(?:\s*,?\s*|\s+)xưởng|kho(?:\s*,?\s*|\s+)xuong"
    r"|văn\s*phòng|van\s*phong|mặt\s*bằng\s*kinh\s*doanh|mat\s*bang\s*kinh\s*doanh"
    r"|bất\s*động\s*sản\s*nghỉ\s*dưỡng|bat\s*dong\s*san\s*nghi\s*duong"
    r")\b",
    re.IGNORECASE,
)
_UNIT_CODE_PATTERN = re.compile(r"\b[A-Z]{1,6}\d{0,3}-[A-Z0-9]{2,12}\b", re.IGNORECASE)
_AREA_RANGE_PATTERN = re.compile(
    r"\b(?:(?:từ|tu)\s*)?(\d+(?:[.,]\d+)?)\s*(?:[-\u2013\u2014]|đến|den|tới|toi)\s*"
    r"(\d+(?:[.,]\d+)?)\s*m(?:2|²)\b",
    re.IGNORECASE,
)
_AREA_MAX_PATTERN = re.compile(
    r"\b(?:dưới|duoi|<=?|không quá|khong qua|tối đa|toi da)\s*(\d+(?:[.,]\d+)?)\s*m(?:2|²)\b",
    re.IGNORECASE,
)
_AREA_MIN_PATTERN = re.compile(r"\b(?:trên|tren|>=?|từ|tu)\s*(\d+(?:[.,]\d+)?)\s*m(?:2|²)\b", re.IGNORECASE)
_PRICE_RANGE_PATTERN = re.compile(
    rf"\b(?:(?:từ|tu)\s*)?(\d+(?:[.,]\d+)?)\s*({BUDGET_UNIT_ALTERNATION_WITH_BARE_T})?\s*"
    rf"(?:-|đến|den|tới|toi)\s*(\d+(?:[.,]\d+)?)\s*({BUDGET_UNIT_ALTERNATION_WITH_BARE_T})\b",
    re.IGNORECASE,
)
_PRICE_MAX_PATTERN = re.compile(
    rf"\b(?:dưới|duoi|<=?|không quá|khong qua|tối đa|toi da)\s*(\d+(?:[.,]\d+)?)\s*"
    rf"({BUDGET_UNIT_ALTERNATION_WITH_BARE_T})\b",
    re.IGNORECASE,
)
_PRICE_MIN_PATTERN = re.compile(
    rf"\b(?:trên|tren|>=?|từ|tu)\s*(\d+(?:[.,]\d+)?)\s*({BUDGET_UNIT_ALTERNATION_WITH_BARE_T})\b",
    re.IGNORECASE,
)
_STATUS_PATTERN = re.compile(
    r"\b(còn căn|con can|còn bán|con ban|còn hàng|con hang|còn trống|con trong|available|"
    r"giữ chỗ|giu cho|đặt chỗ|dat cho|reserved|đã bán|da ban|sold)\b",
    re.IGNORECASE,
)
_STATUS_ALIASES = {
    "còn căn": "available",
    "con can": "available",
    "còn bán": "available",
    "con ban": "available",
    "còn hàng": "available",
    "con hang": "available",
    "còn trống": "available",
    "con trong": "available",
    "available": "available",
    "giữ chỗ": "reserved",
    "giu cho": "reserved",
    "đặt chỗ": "reserved",
    "dat cho": "reserved",
    "reserved": "reserved",
    "đã bán": "sold",
    "da ban": "sold",
    "sold": "sold",
}

_DIRECTION_QUERY_PATTERN = re.compile(
    r"\b(?:hướng|huong)\s+"
    r"(đông\s+nam|dong\s+nam|đông\s+bắc|dong\s+bac|tây\s+nam|tay\s+nam|"
    r"tây\s+bắc|tay\s+bac|đông|dong|tây|tay|nam|bắc|bac)\b",
    re.IGNORECASE,
)
_TOWER_QUERY_PATTERN = re.compile(r"\b(?:toa|tower)\s+([a-z]{1,6}\d+(?:[.-]\d+)?)\b", re.IGNORECASE)
_FLOOR_QUERY_PATTERN = re.compile(r"\b(?:tang|floor)\s+([a-z]?\d+[a-z]?)\b", re.IGNORECASE)
_VIEW_QUERY_PATTERN = re.compile(
    r"\bview\s+(.+?)(?=\s+(?:và|va|nhưng|nhung|trong|tại|tai|với|voi|"
    r"ưu\s+tiên|uu\s+tien|bắt\s+buộc|bat\s+buoc)\b|[,.;?]|$)",
    re.IGNORECASE,
)
_VAGUE_VIEW_TERMS = {"dep", "thoang", "rong", "tot", "xin"}
_MANDATORY_QUERY_PATTERN = re.compile(r"\b(?:phai|bat buoc|nhat dinh|chi lay|chi xem|chi muon)\b", re.IGNORECASE)


class InventoryApiError(Exception):
    """Lost connection to, or a bad response from, the internal inventory API."""


class InventoryProjectUnresolvedError(InventoryApiError):
    """The API was never called: no project on the session and no '*' catch-all, so which
    project's stock to check is genuinely unknown.

    Its own subclass so `agent_pipeline._tool_call` can tell "the inventory is down" (a
    hiccup to apologise for) from "ask which project first" (a normal follow-up question).
    """


@dataclass
class InventoryUnit:
    unit_code: str
    project_id: str
    subdivision: str | None
    unit_type: str | None
    area_m2: float | None
    price: float | None
    status: str
    tower: str | None = None
    floor: str | None = None
    direction: str | None = None
    view_type: tuple[str, ...] = ()


def lookup_inventory(
    project_id: str | None,
    query: str,
    context_queries: list[str] | None = None,
) -> list[InventoryUnit]:
    """Look up a project's inventory, filtered by the unit type mentioned in the question.

    `project_id` is the catalogue slug on the session, or None — a normal case, since the
    session flow no longer asks the Sale to pick a project and the catch-all decides.

    `context_queries` holds recent questions, newest first: an explicit filter in the
    current query wins, a missing one is inherited, so "diện tích 45-70m2" stays scoped to
    the "2 ngủ ở The Sapphire" asked before it.

    An empty list means "sold out", never "lookup failed" — conflating the two would show
    "Tạm thời không tra được tồn kho" while the API is perfectly healthy. Raises
    `InventoryProjectUnresolvedError` or `InventoryApiError` when data cannot be fetched.
    """
    return _apply_query_filters(fetch_units(project_id), query, context_queries=context_queries)


def fetch_units(project_id: str | None) -> list[InventoryUnit]:
    """Every unit of a project, unfiltered — the raw set before any question narrows it.

    Split out of `lookup_inventory` because zero-result diagnosis re-filters the same set
    repeatedly, dropping one criterion at a time; going through `lookup_inventory` would
    re-call the API each attempt. Raises the same two errors.
    """
    api_project_id = resolve_api_project_id(project_id)
    if api_project_id is None:
        raise InventoryProjectUnresolvedError(
            "No inventory project id: the session carries no project and "
            "INVENTORY_PROJECT_MAP defines no '*' catch-all."
        )

    payload = _fetch_units(api_project_id)

    units = [unit for unit in (_parse_unit(item) for item in payload) if unit is not None]
    units = [unit for unit in units if unit.project_id == api_project_id]
    return _scope_to_slug_subdivision(units, project_id)


def _scope_to_slug_subdivision(units: list[InventoryUnit], project_id: str | None) -> list[InventoryUnit]:
    """Narrow an API project's rows to the subdivision the catalogue slug names.

    Many slugs share one API code (every Ocean Park sub-zone is `ocp1`, separated only by
    `subdivision`), so returning the whole row set would answer "what's left at The
    Pavilion" with Ngọc Trai units relabelled as Pavilion stock.

    Only an explicitly mapped slug is scoped; one resolved through `*` is a deliberately
    whole-project search. A mapped slug matching no subdivision returns [] — a truthful
    "no units" rather than another project's stock.
    """
    if not has_exact_project_mapping(project_id):
        return units

    if project_id is None:
        raise ValueError("An exact inventory mapping requires a project id.")
    slug_text = project_id.replace("-", " ")
    wanted = {
        _normalize_text(unit.subdivision)
        for unit in units
        if unit.subdivision and any(alias and alias in slug_text for alias in _subdivision_aliases(unit.subdivision))
    }
    if not wanted:
        return []
    return [unit for unit in units if _normalize_text(unit.subdivision) in wanted]


def resolve_api_project_id(project_id: str | None) -> str | None:
    """Translate a catalogue slug into the inventory API's own project code.

    Two different namespaces: `projects.id` is a per-sub-zone slug, while the API groups
    them under one code and exposes the sub-zone as `subdivision`. An unmapped slug 404s.

    None means nothing resolved, which `fetch_units` turns into
    `InventoryProjectUnresolvedError`.
    """
    mapping = _project_map()

    if project_id:
        return mapping.get(project_id) or mapping.get("*") or project_id

    return mapping.get("*")


def has_exact_project_mapping(project_id: str | None) -> bool:
    """True only when live inventory explicitly maps this catalogue project.

    A `*` mapping is fine for a broad search but is no evidence that those rows belong to a
    named subdivision — treating it as such once showed CT1/CT2 units under The Pavilion.
    """
    return bool(project_id and project_id in _project_map())


def _project_map() -> dict[str, str]:
    """Parse INVENTORY_PROJECT_MAP ("slug=code, *=code") into a dict.

    Malformed entries are skipped with a warning rather than raising: a typo in one pair
    must not take down inventory lookups for every other project.
    """
    raw = settings.inventory_project_map
    if not raw:
        return {}

    mapping: dict[str, str] = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        key, separator, value = entry.partition("=")
        key, value = key.strip(), value.strip()
        if not separator or not key or not value:
            logger.warning(
                "Skipping a malformed INVENTORY_PROJECT_MAP entry.",
                extra={"event": "inventory.project_map.invalid_entry", "entry": entry},
            )
            continue
        mapping[key] = value

    return mapping


def _fetch_units(project_id: str) -> list:
    """Call the inventory API and return the raw payload, guaranteed to be a list."""
    if not settings.inventory_api_url:
        raise InventoryApiError("INVENTORY_API_URL is not configured.")

    headers = {}
    if settings.inventory_api_key:
        headers["Authorization"] = f"Bearer {settings.inventory_api_key}"

    try:
        response = httpx.get(
            settings.inventory_api_url,
            params={"project_id": project_id},
            headers=headers,
            timeout=INVENTORY_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as exc:
        raise InventoryApiError(f"Inventory API unreachable: {exc}") from exc
    except ValueError as exc:
        raise InventoryApiError("Inventory API returned a body that is not JSON.") from exc

    if not isinstance(payload, list):
        raise InventoryApiError(f"Inventory API returned {type(payload).__name__}, expected a list.")

    return payload


_FIELD_NAMES = {field.name for field in fields(InventoryUnit)}


def _parse_unit(item: object) -> InventoryUnit | None:
    """Turn a raw record into an `InventoryUnit`, or None when it is unusable.

    Skips bad rows rather than raising: the API carries extra fields or omits one, and a
    single dirty row must not fail the whole lookup.
    """
    if not isinstance(item, dict):
        logger.warning(
            "Skipping an inventory record that is not an object.",
            extra={"event": "inventory.record.not_dict", "record_type": type(item).__name__},
        )
        return None

    data = {key: value for key, value in item.items() if key in _FIELD_NAMES}
    if not {"unit_code", "project_id", "status"} <= data.keys():
        logger.warning(
            "Skipping an inventory record missing required fields.",
            extra={
                "event": "inventory.record.incomplete",
                "missing_fields": sorted({"unit_code", "project_id", "status"} - data.keys()),
            },
        )
        return None

    unit_type = data.get("unit_type")
    subdivision = data.get("subdivision")
    tower = data.get("tower")
    floor = data.get("floor")
    direction = data.get("direction")
    return InventoryUnit(
        unit_code=sanitize_external_field(str(data["unit_code"])),
        project_id=sanitize_external_field(str(data["project_id"])),
        subdivision=sanitize_external_field(str(subdivision)) if subdivision is not None else None,
        unit_type=sanitize_external_field(str(unit_type)) if unit_type is not None else None,
        area_m2=_to_float(data.get("area_m2")),
        price=_to_float(data.get("price")),
        status=sanitize_external_field(str(data["status"])),
        tower=sanitize_external_field(str(tower)) if tower is not None else None,
        floor=sanitize_external_field(str(floor)) if floor is not None else None,
        direction=sanitize_external_field(str(direction)) if direction is not None else None,
        view_type=_parse_view_field(data.get("view_type")),
    )


def _parse_view_field(value: object) -> tuple[str, ...]:
    """Normalise an API view field that may be one string or a JSON list."""
    raw_values: list[object]
    if isinstance(value, list | tuple | set):
        raw_values = list(value)
    elif value is None:
        raw_values = []
    else:
        raw_values = re.split(r"\s*[,|/]\s*", str(value))
    return tuple(
        dict.fromkeys(cleaned for item in raw_values if (cleaned := sanitize_external_field(str(item)).strip()))
    )


def _to_float(value: object) -> float | None:
    """Price arrives as a number or a string depending on the API; a bad price is left
    blank rather than discarding the whole unit."""
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        logger.debug(
            "Unreadable inventory price; leaving it blank.",
            extra={"event": "inventory.price.unparseable", "value_type": type(value).__name__},
        )
        return None


def _extract_unit_types(query: str) -> list[str]:
    """Extract every explicitly named type, preserving broad category aliases.

    A broad "biệt thự" stays `BIETTHU`, which `unit_type_matches` expands to BT_DL/BT_SL/LK
    — the wording is kept intact while still matching the API codes.
    """
    return list(
        dict.fromkeys(
            normalized
            for match in _UNIT_TYPE_PATTERN.finditer(query)
            if (normalized := _normalize_unit_type(match.group(0))) is not None
        )
    )


def _extract_unit_type_mentions(query: str) -> list[tuple[str, bool]]:
    """Types with a local exclusion flag ("nhà phố, không lấy chung cư")."""
    mentions: list[tuple[str, bool]] = []
    for match in _UNIT_TYPE_PATTERN.finditer(query):
        normalized = _normalize_unit_type(match.group(0))
        if normalized is None:
            continue
        prefix = _normalize_text(query[max(0, match.start() - 28) : match.start()])
        excluded = bool(
            re.search(
                r"(?:khong (?:lay|chon|muon)(?: (?:loai|can))?|loai tru(?: can)?|tranh(?: can)?)\s*$",
                prefix,
            )
        )
        if re.fullmatch(r"\d+PN\+?", normalized):
            if re.search(r"(?:it nhat|toi thieu|tu)\s*$", prefix):
                normalized = f"MIN{normalized}"
            elif re.search(r"(?:toi da|khong qua)\s*$", prefix):
                normalized = f"MAX{normalized}"
        mentions.append((normalized, excluded))
    return list(dict.fromkeys(mentions))


def _normalize_unit_type(unit_type: str | None) -> str | None:
    """Normalise customer labels and API codes to one canonical vocabulary."""
    if unit_type is None:
        return None

    normalized = _normalize_text(unit_type)
    bedroom_match = re.fullmatch(r"(\d+)\s*(?:pn|br|phong\s*ngu|ngu)(?:\s*\+\s*(?:1)?)?", normalized)
    if bedroom_match:
        suffix = "+" if "+" in normalized else ""
        return f"{bedroom_match.group(1)}PN{suffix}"

    compact = re.sub(r"[\s_-]+", "", normalized).upper()
    aliases = {
        "CANHO": "CANHO",
        "CHUNGCU": "CANHO",
        "BIETTHU": "BIETTHU",
        "BIETTHUDONLAP": "BT_DL",
        "DONLAP": "BT_DL",
        "BTDL": "BT_DL",
        "BIETTHUSONGLAP": "BT_SL",
        "SONGLAP": "BT_SL",
        "BTSL": "BT_SL",
        "BIETTHULIENKE": "LK",
        "LIENKE": "LK",
        "NHAPHO": "LK",
        "NHAPHOTHUONGMAI": "SH",
        "SHOPTHUONGMAI": "SH",
        "SHOPHOUSE": "SH",
        "NHARIENG": "NHARIENG",
        "NHAHEM": "NHAHEM",
        "NHATRONGHEM": "NHAHEM",
        "NHANGO": "NHAHEM",
        "NHATRONGNGO": "NHAHEM",
        "NHAMATTIEN": "NHAMATTIEN",
        "NHACAP4": "NHACAP4",
        "PHONGTRO": "PHONGTRO",
        "NHANGUYENCAN": "NHANGUYENCAN",
        "DATNEN": "DATNEN",
        "DATTHOCU": "DATTHOCU",
        "DATDUAN": "DATDUAN",
        "TRANGTRAI": "NHAVUON",
        "NHAVUON": "NHAVUON",
        "KHOXUONG": "KHOXUONG",
        "VANPHONG": "VANPHONG",
        "MATBANGKINHDOANH": "MATBANG",
        "BATDONGSANNGHIDUONG": "NGHIDUONG",
    }
    return aliases.get(compact, compact)


def unit_type_matches(actual: str | None, wanted: str | None) -> bool:
    """Whether one API/catalogue type satisfies a normalized requested type."""
    actual_type = _normalize_unit_type(actual)
    wanted_type = _normalize_unit_type(wanted)
    if actual_type is None or wanted_type is None:
        return False
    if actual_type == wanted_type:
        return True
    if re.fullmatch(r"\d+PN", wanted_type) and actual_type == f"{wanted_type}+":
        return True
    minimum = re.fullmatch(r"MIN(\d+)PN\+?", wanted_type)
    maximum = re.fullmatch(r"MAX(\d+)PN\+?", wanted_type)
    actual_bedrooms = re.fullmatch(r"(\d+)PN\+?", actual_type)
    if minimum and actual_bedrooms:
        return int(actual_bedrooms.group(1)) >= int(minimum.group(1))
    if maximum and actual_bedrooms:
        return int(actual_bedrooms.group(1)) <= int(maximum.group(1))
    if wanted_type == "CANHO":
        return bool(re.fullmatch(r"\d+PN\+?", actual_type)) or actual_type in {
            "STUDIO",
            "PENTHOUSE",
            "DUPLEX",
            "OFFICETEL",
        }
    if wanted_type == "BIETTHU":
        return actual_type in {"BT_DL", "BT_SL", "LK"}
    return False


def apply_criteria(units: list[InventoryUnit], criteria) -> list[InventoryUnit]:
    """Filter units by accumulated criteria rather than by one question's text.

    Takes a `search_criteria.SearchCriteria` but is typed loosely on purpose: that module
    imports this one, so importing it back would be a cycle. Only HARD and EXCLUDED
    constraints reach here — SOFT ones rank, never exclude.
    """
    for constraint in criteria.filtering():
        if str(constraint.strength) == "excluded":
            matched_ids = {id(unit) for unit in _apply_one(units, constraint.field, constraint.value)}
            units = [unit for unit in units if id(unit) not in matched_ids]
        else:
            units = _apply_one(units, constraint.field, constraint.value)
    sort_by = getattr(criteria, "sort_by", None)
    if not sort_by:
        units = _rank_soft_matches(units, getattr(criteria, "constraints", ()))
    return _sort_units(units, sort_by)


def _rank_soft_matches(units: list[InventoryUnit], constraints) -> list[InventoryUnit]:
    """Stable rank: confirmed preference match, unknown data, confirmed mismatch."""
    soft = [constraint for constraint in constraints if str(constraint.strength) == "soft"]
    if not soft:
        return units

    def score(unit: InventoryUnit) -> int:
        return sum(_soft_match_score(unit, item.field, item.value) for item in soft)

    return sorted(units, key=score, reverse=True)


def _soft_match_score(unit: InventoryUnit, field_name: str, value) -> int:
    field_values = {
        "directions": [unit.direction] if unit.direction else [],
        "views": list(unit.view_type),
        "towers": [unit.tower] if unit.tower else [],
        "floors": [unit.floor] if unit.floor else [],
    }.get(field_name)
    if field_values is None:
        return 2 if unit in _apply_one([unit], field_name, value) else 0
    if not field_values:
        return 1
    wanted = {_normalize_text(item) for item in value}
    actual = {_normalize_text(item) for item in field_values}
    return 2 if wanted & actual else 0


def format_preference_coverage(units: list[InventoryUnit], criteria) -> str:
    """Ground the distinction between confirmed, unknown and mismatched preferences."""
    tracked_fields = {"directions", "views", "towers", "floors"}
    preferences = [
        item
        for item in getattr(criteria, "constraints", ())
        if str(item.strength) == "soft" and item.field in tracked_fields
    ]
    if not units or not preferences:
        return ""

    lines = ["ĐỘ PHỦ TIÊU CHÍ ƯU TIÊN TRONG TỒN KHO:"]
    for constraint in preferences:
        scores = [_soft_match_score(unit, constraint.field, constraint.value) for unit in units]
        confirmed = sum(score == 2 for score in scores)
        unknown = sum(score == 1 for score in scores)
        mismatch = sum(score == 0 for score in scores)
        lines.append(
            f"- {constraint.field}={', '.join(str(item) for item in constraint.value)}: "
            f"{confirmed} căn xác nhận khớp; {unknown} căn thiếu dữ liệu; {mismatch} căn xác nhận không khớp."
        )
    lines.append(
        "Xếp căn xác nhận khớp trước, sau đó mới đến căn thiếu dữ liệu. Không biến 'thiếu dữ liệu' "
        "thành 'không phù hợp'; phải ghi rõ đó là kết quả khớp một phần cần xác minh thêm."
    )
    return "\n".join(lines)


def _sort_units(units: list[InventoryUnit], sort_by: str | None) -> list[InventoryUnit]:
    """Apply only orderings supported by fields that really exist on InventoryUnit."""
    if sort_by == "price_asc":
        return sorted(units, key=lambda unit: (unit.price is None, unit.price or 0))
    if sort_by == "price_desc":
        return sorted(units, key=lambda unit: (unit.price is None, -(unit.price or 0)))
    if sort_by == "area_desc":
        return sorted(units, key=lambda unit: (unit.area_m2 is None, -(unit.area_m2 or 0)))
    if sort_by == "price_per_m2_asc":
        return sorted(
            units,
            key=lambda unit: (
                unit.price is None or not unit.area_m2,
                unit.price / unit.area_m2 if unit.price is not None and unit.area_m2 else 0,
            ),
        )
    return units


def _apply_one(units: list[InventoryUnit], field_name: str, value) -> list[InventoryUnit]:
    """Apply a single constraint. Unknown fields filter nothing — criteria carry advisory
    entries with no InventoryUnit counterpart, which must pass through rather than empty
    the result."""
    if field_name == "unit_types":
        return [unit for unit in units if any(unit_type_matches(unit.unit_type, item) for item in value)]

    if field_name == "unit_codes":
        wanted = {str(item).strip().casefold() for item in value}
        return [unit for unit in units if unit.unit_code.strip().casefold() in wanted]

    if field_name == "subdivisions":
        wanted = {_normalize_text(item) for item in value}
        return [unit for unit in units if _normalize_text(unit.subdivision) in wanted]

    if field_name == "statuses":
        wanted = {str(item).strip().lower() for item in value}
        return [unit for unit in units if unit.status.strip().lower() in wanted]

    if field_name == "price":
        minimum, maximum = value
        return [unit for unit in units if unit.price is not None and minimum <= unit.price <= maximum]

    if field_name == "area":
        minimum, maximum = value
        return [unit for unit in units if unit.area_m2 is not None and minimum <= unit.area_m2 <= maximum]

    if field_name == "directions":
        wanted = {_normalize_text(item) for item in value}
        return [unit for unit in units if unit.direction and _normalize_text(unit.direction) in wanted]

    if field_name == "views":
        wanted = {_normalize_text(item) for item in value}
        return [unit for unit in units if wanted & {_normalize_text(item) for item in unit.view_type}]

    if field_name == "towers":
        wanted = {_normalize_text(item) for item in value}
        return [unit for unit in units if unit.tower and _normalize_text(unit.tower) in wanted]

    if field_name == "floors":
        wanted = {_normalize_text(item) for item in value}
        return [unit for unit in units if unit.floor and _normalize_text(unit.floor) in wanted]

    return units


def _apply_query_filters(
    units: list[InventoryUnit],
    query: str,
    *,
    context_queries: list[str] | None = None,
) -> list[InventoryUnit]:
    """Apply current and inherited natural-language filters with AND semantics.

    The stateless path: recent context only fills in fields the current turn omitted. The
    stateful path goes through `apply_criteria` instead.
    """
    filter_queries = [query, *(context_queries or [])]

    source_units = list(units)
    wanted_codes = next(
        (codes for value in filter_queries if (codes := _extract_unit_codes(value, source_units))),
        set(),
    )
    if wanted_codes:
        units = [unit for unit in units if unit.unit_code in wanted_codes]

    wanted_subdivisions = next(
        (subdivisions for value in filter_queries if (subdivisions := _extract_subdivisions(value, source_units))),
        set(),
    )
    if wanted_subdivisions:
        units = [unit for unit in units if _normalize_text(unit.subdivision) in wanted_subdivisions]

    type_mentions = next(
        (mentions for value in filter_queries if (mentions := _extract_unit_type_mentions(value))),
        [],
    )
    wanted_types = [item for item, excluded in type_mentions if not excluded]
    excluded_types = [item for item, excluded in type_mentions if excluded]
    if wanted_types:
        units = [unit for unit in units if any(unit_type_matches(unit.unit_type, item) for item in wanted_types)]
    if excluded_types:
        units = [unit for unit in units if not any(unit_type_matches(unit.unit_type, item) for item in excluded_types)]

    area_range = next(
        (area for filter_query in filter_queries if (area := _extract_area_range(filter_query)) is not None),
        None,
    )
    if area_range is not None:
        minimum, maximum = area_range
        units = [unit for unit in units if unit.area_m2 is not None and minimum <= unit.area_m2 <= maximum]

    price_range = next(
        (price for filter_query in filter_queries if (price := _extract_price_range(filter_query)) is not None),
        None,
    )
    if price_range is not None:
        minimum, maximum = price_range
        units = [unit for unit in units if unit.price is not None and minimum <= unit.price <= maximum]

    wanted_status = next(
        (status for filter_query in filter_queries if (status := _extract_status(filter_query)) is not None),
        None,
    )
    if wanted_status is not None:
        units = [unit for unit in units if unit.status.strip().lower() == wanted_status]

    tower = _extract_tower(query)
    if tower is not None:
        units = _apply_one(units, "towers", [tower])
    floor = _extract_floor(query)
    if floor is not None:
        units = _apply_one(units, "floors", [floor])

    preferences: list[tuple[str, list[str]]] = []
    direction = _extract_direction(query)
    if direction is not None:
        preferences.append(("directions", [direction]))
    views = _extract_view_types(query)
    if views:
        preferences.append(("views", views))
    if preferences:
        if _MANDATORY_QUERY_PATTERN.search(_normalize_text(query)):
            for field_name, value in preferences:
                units = _apply_one(units, field_name, value)
        else:
            units = sorted(
                units,
                key=lambda unit: sum(_soft_match_score(unit, field_name, value) for field_name, value in preferences),
                reverse=True,
            )
    return units


def _extract_unit_codes(query: str, units: list[InventoryUnit]) -> set[str]:
    """Exact unit codes mentioned in the query; supports contextual follow-ups."""

    normalized_query = _normalize_text(query)
    return {
        unit.unit_code
        for unit in units
        if unit.unit_code
        and re.search(
            rf"(?<![a-z0-9]){re.escape(_normalize_text(unit.unit_code))}(?![a-z0-9])",
            normalized_query,
        )
    }


def _subdivision_aliases(subdivision: str) -> set[str]:
    """Safe human aliases for one subdivision.

    The API stores "The Sapphire 1" and "2" separately while people ask for the parent
    name. Dropping only a leading "The" and a trailing number keeps this deterministic
    instead of fuzzy-matching unrelated projects.
    """

    normalized = _normalize_text(subdivision)
    aliases = {normalized}
    if normalized.startswith("the "):
        aliases.add(normalized[4:])

    for alias in tuple(aliases):
        parent = re.sub(r"\s+\d+$", "", alias).strip()
        if parent:
            aliases.add(parent)
    return aliases


def _extract_subdivisions(query: str, units: list[InventoryUnit]) -> set[str]:
    """Resolve the most specific subdivision alias mentioned in the query.

    Multiple stored children may intentionally share the winning alias: "The Sapphire"
    selects both Sapphire 1 and 2, while "Sapphire 1" selects only that child.
    """

    normalized_query = _normalize_text(query)
    subdivision_aliases: dict[str, set[str]] = {}
    for unit in units:
        if not unit.subdivision:
            continue
        normalized_subdivision = _normalize_text(unit.subdivision)
        subdivision_aliases.setdefault(normalized_subdivision, _subdivision_aliases(unit.subdivision))

    matches = [
        (len(alias), alias, subdivision)
        for subdivision, aliases in subdivision_aliases.items()
        for alias in aliases
        if alias and alias in normalized_query
    ]
    if not matches:
        return set()

    most_specific_length = max(length for length, _, _ in matches)
    return {subdivision for length, _, subdivision in matches if length == most_specific_length}


def _extract_unit_code(query: str) -> str | None:
    match = _UNIT_CODE_PATTERN.search(query)
    return match.group(0).upper() if match else None


def _extract_direction(query: str) -> str | None:
    match = _DIRECTION_QUERY_PATTERN.search(query)
    return match.group(1) if match else None


def _extract_view_types(query: str) -> list[str]:
    values: list[str] = []
    for match in _VIEW_QUERY_PATTERN.finditer(query):
        for raw_value in re.split(r"\s+(?:hoặc|hoac)\s+", match.group(1), flags=re.IGNORECASE):
            value = " ".join(raw_value.split())
            if value and _normalize_text(value) not in _VAGUE_VIEW_TERMS:
                values.append(value)
    return list(dict.fromkeys(values))


def _extract_tower(query: str) -> str | None:
    match = _TOWER_QUERY_PATTERN.search(_normalize_text(query))
    return match.group(1) if match else None


def _extract_floor(query: str) -> str | None:
    match = _FLOOR_QUERY_PATTERN.search(_normalize_text(query))
    return match.group(1) if match else None


def _extract_area_range(query: str) -> tuple[float, float] | None:
    match = _AREA_RANGE_PATTERN.search(query)
    if match:
        return _ordered_range(_to_number(match.group(1)), _to_number(match.group(2)))
    match = _AREA_MAX_PATTERN.search(query)
    if match:
        return 0.0, _to_number(match.group(1))
    match = _AREA_MIN_PATTERN.search(query)
    if match:
        return _to_number(match.group(1)), float("inf")
    return None


def _extract_price_range(query: str) -> tuple[float, float] | None:
    match = _PRICE_RANGE_PATTERN.search(query)
    if match:
        return _ordered_range(
            _price_to_vnd(match.group(1), match.group(2)), _price_to_vnd(match.group(3), match.group(4))
        )
    match = _PRICE_MAX_PATTERN.search(query)
    if match:
        return 0.0, _price_to_vnd(match.group(1), match.group(2))
    match = _PRICE_MIN_PATTERN.search(query)
    if match:
        return _price_to_vnd(match.group(1), match.group(2)), float("inf")
    return None


def _extract_status(query: str) -> str | None:
    match = _STATUS_PATTERN.search(query)
    return _STATUS_ALIASES[match.group(1).lower()] if match else None


def _normalize_text(text: str | None) -> str:
    lowered = (text or "").casefold().replace("đ", "d")
    unaccented = "".join(char for char in unicodedata.normalize("NFD", lowered) if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", unaccented).strip()


def _to_number(value: str) -> float:
    return float(value.replace(",", "."))


def _price_to_vnd(value: str, unit: str | None) -> float:
    """Thin adapter over the shared parser; callers here compare against float bounds.

    Kept as a float-returning wrapper rather than churning `_extract_price_range`, whose
    open-ended bounds are `float("inf")` sentinels. Unparseable input used to raise
    ValueError — "1.500.000" did, and no caller had a branch for it — so it now falls back
    to 0.0, which the range comparisons already treat as "no lower bound".
    """
    dong = parse_vnd(value, unit, profile=Profile.CONVERSATIONAL)
    return float(dong) if dong is not None else 0.0


def _ordered_range(first: float, second: float) -> tuple[float, float]:
    return min(first, second), max(first, second)
