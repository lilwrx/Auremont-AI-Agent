"""Search criteria — the filters a person has built up over a conversation.

`inventory_service` parses one question and forgets it, which drops "giữ nguyên điều
kiện, tăng giá lên 5 tỷ"'s earlier 3PN filter. This module is that missing state, merged
turn by turn.

Differs from the memory modules next to it: `memory_service` stores durable hints about a
*person* and refuses the multi-figure sentences this one must parse; criteria are hard
constraints, not hints. TTL is 24h, not 90 days — a stale filter from yesterday would
invisibly hide units today. Three strengths, not one flat AND: "bắt buộc" excludes, "ưu
tiên" only ranks.

Fails open like every Redis-backed module here — losing criteria costs a repeated
sentence, never a wrong number, since grounding still comes from inventory and documents.
Deterministic regex throughout: this runs on every filtering question, so a model call
would add a failure mode to the hot path.
"""

import json
import logging
import re
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import combinations
from typing import Any

from backend.core.config import get_settings
from backend.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)


def session_key(session_id: int) -> str:
    return f"search:session:{session_id}"


MAX_HISTORY_SNAPSHOTS = 5

MAX_DIAGNOSIS_CONSTRAINTS = 8


class Strength(StrEnum):
    """How binding a criterion is — the split cases.md calls out as the thing that decides
    whether a search returns nothing or returns the wrong thing."""

    HARD = "hard"
    SOFT = "soft"
    EXCLUDED = "excluded"


class Source(StrEnum):
    """Where a criterion came from, which decides what may be relaxed when nothing matches.

    `INFERRED` was this module's own guess at a vague phrase ("tầm 3 tỷ" -> ±15%), so
    widening it later corrects the guess. `EXPLICIT` is what they typed and must never be
    dropped on their behalf.
    """

    EXPLICIT = "explicit"
    INFERRED = "inferred"


FIELD_UNIT_TYPES = "unit_types"
FIELD_UNIT_CODES = "unit_codes"
FIELD_SUBDIVISIONS = "subdivisions"
FIELD_PRICE = "price"
FIELD_AREA = "area"
FIELD_STATUSES = "statuses"
FIELD_DIRECTIONS = "directions"
FIELD_VIEWS = "views"
FIELD_TOWERS = "towers"
FIELD_FLOORS = "floors"


@dataclass(frozen=True)
class Constraint:
    """One criterion plus how binding it is.

    `value` is a `(min, max)` tuple for the range fields (price, area) and a list of
    accepted strings for the rest. Frozen so a snapshot pushed onto the undo stack cannot
    be mutated from under it.
    """

    field: str
    value: Any
    strength: Strength = Strength.HARD
    source: Source = Source.EXPLICIT

    def describe(self) -> str:
        """One short Vietnamese phrase, for the prompt and for zero-result diagnosis."""
        if self.field == FIELD_PRICE:
            return f"giá {_describe_range(self.value, _format_price)}"
        if self.field == FIELD_AREA:
            return f"diện tích {_describe_range(self.value, _format_area)}"
        if self.field == FIELD_UNIT_TYPES:
            return f"loại căn {', '.join(_display_unit_type(item) for item in self.value)}"
        if self.field == FIELD_UNIT_CODES:
            return f"mã căn {', '.join(self.value)}"
        if self.field == FIELD_SUBDIVISIONS:
            return f"phân khu {', '.join(self.value)}"
        if self.field == FIELD_STATUSES:
            return f"tình trạng {', '.join(self.value)}"
        if self.field == FIELD_DIRECTIONS:
            return f"hướng {', '.join(self.value)}"
        if self.field == FIELD_VIEWS:
            return f"view {', '.join(self.value)}"
        if self.field == FIELD_TOWERS:
            return f"tòa {', '.join(self.value)}"
        if self.field == FIELD_FLOORS:
            return f"tầng {', '.join(self.value)}"
        return f"{self.field}: {self.value}"


@dataclass(frozen=True)
class SearchCriteria:
    """Everything asked for so far in one consultation.

    `constraints` runs against real InventoryUnit fields. The feature/purpose/household
    fields have no corresponding field on InventoryUnit — they ride into the prompt for the
    model to weigh, and never filter here. Adding them to `apply_criteria` would silently
    match nothing.
    """

    constraints: tuple[Constraint, ...] = ()
    required_features: tuple[str, ...] = ()
    preferred_features: tuple[str, ...] = ()
    excluded_features: tuple[str, ...] = ()
    purpose: str | None = None
    household_size: int | None = None
    sort_by: str | None = None

    def is_empty(self) -> bool:
        return not (
            self.constraints
            or self.required_features
            or self.preferred_features
            or self.excluded_features
            or self.purpose
            or self.household_size
            or self.sort_by
        )

    def get(self, field_name: str) -> Constraint | None:
        for constraint in self.constraints:
            if constraint.field == field_name:
                return constraint
        return None

    def filtering(self) -> tuple[Constraint, ...]:
        """Constraints that actually exclude units — HARD and EXCLUDED, never SOFT."""
        return tuple(c for c in self.constraints if c.strength in (Strength.HARD, Strength.EXCLUDED))


class Intent(StrEnum):
    """What the person is doing to their criteria this turn."""

    REFINE = "refine"
    DROP = "drop"
    RESET = "reset"
    UNDO = "undo"


@dataclass(frozen=True)
class CriteriaDelta:
    """What one question said, before it is merged into what came before."""

    intent: Intent = Intent.REFINE
    constraints: tuple[Constraint, ...] = ()
    dropped_fields: tuple[str, ...] = ()
    required_features: tuple[str, ...] = ()
    preferred_features: tuple[str, ...] = ()
    excluded_features: tuple[str, ...] = ()
    household_size: int | None = None
    purpose: str | None = None
    sort_by: str | None = None
    unresolved_vague: tuple[str, ...] = ()

    def is_empty(self) -> bool:
        return not (
            self.constraints
            or self.dropped_fields
            or self.required_features
            or self.preferred_features
            or self.excluded_features
            or self.household_size
            or self.purpose
            or self.sort_by
            or self.intent != Intent.REFINE
        )


@dataclass(frozen=True)
class RelaxOption:
    """One deterministic way to make an empty result set non-empty again."""

    removed: tuple[Constraint, ...]
    estimated_count: int


@dataclass(frozen=True)
class ZeroResultDiagnosis:
    """Counts grounding the explanation shown when the active filters match no unit."""

    total_units: int
    active_constraints: tuple[Constraint, ...]
    relax_options: tuple[RelaxOption, ...]


from backend.services import inventory_service as _inv  # noqa: E402
from backend.utils.vnd import BUDGET_UNIT_ALTERNATION, Profile, parse_vnd  # noqa: E402

_MANDATORY_PATTERN = re.compile(r"\b(phải|bắt buộc|nhất định|chỉ lấy|chỉ xem|chỉ muốn)\b", re.IGNORECASE)

_RESET_PATTERN = re.compile(
    r"(xoá|xóa|bỏ)\s*(hết|toàn bộ|tất cả)?\s*(bộ lọc|điều kiện|tiêu chí)"
    r"|tìm lại từ đầu|làm lại từ đầu|bắt đầu lại",
    re.IGNORECASE,
)
_UNDO_PATTERN = re.compile(
    r"(quay lại|trở lại|khôi phục)\s*(bộ lọc|điều kiện|tiêu chí)?\s*(cũ|trước|ban đầu)"
    r"|như (lúc nãy|ban đầu|trước đó)",
    re.IGNORECASE,
)
_DROP_PATTERN = re.compile(
    r"(bỏ|huỷ|hủy|không cần|thôi không|bỏ qua)\s+(yêu cầu|điều kiện|tiêu chí)?\s*",
    re.IGNORECASE,
)
_EXCLUDE_PATTERN = re.compile(
    r"\b(không lấy|không chọn|loại trừ|tránh|khong lay|khong chon|loai tru|tranh)\b",
    re.IGNORECASE,
)
_LOCATION_EXCLUDE_PREFIX = re.compile(
    r"(?:\bngoài\b(?!\s+ra\b)|\bngoai\b(?!\s+ra\b)|\btrừ\b|\btru\b|\bkhông phải\b|\bkhong phai\b|"
    r"\bkhông lấy\b|\bkhong lay\b|\bkhông chọn\b|\bkhong chon\b|"
    r"\bloại trừ\b|\bloai tru\b|\btránh\b|\btranh\b|\bkhác với\b|\bkhac voi\b)"
    r"(?:\s+\w+){0,5}\s*$",
    re.IGNORECASE,
)

_RAISE_PATTERN = re.compile(
    r"\b(?:tăng|nâng|lên|tang|nang|len)\s*"
    r"(?:(?:giá|gia|ngân sách|ngan sach)\s*)?(?:(?:lên|len|tới|toi|đến|den)\s*)?"
    rf"(\d+(?:[.,]\d+)?)\s*({BUDGET_UNIT_ALTERNATION})\b",
    re.IGNORECASE,
)
_LOWER_PATTERN = re.compile(
    r"\b(?:giảm|hạ|xuống|giam|ha|xuong)\s*"
    r"(?:(?:giá|gia|ngân sách|ngan sach)\s*)?(?:(?:xuống|xuong|còn|con)\s*)?"
    rf"(\d+(?:[.,]\d+)?)\s*({BUDGET_UNIT_ALTERNATION})\b",
    re.IGNORECASE,
)
_AREA_ADJUST_PATTERN = re.compile(
    r"\b(?:tăng|nâng|giảm|hạ|lên|xuống|tang|nang|giam|ha|len|xuong)\s*"
    r"(?:(?:diện tích|dien tich)\s*)?(?:(?:lên|len|xuống|xuong|còn|con)\s*)?"
    r"(\d+(?:[.,]\d+)?)\s*m(?:2|²)\b",
    re.IGNORECASE,
)

_VAGUE_AROUND_PATTERN = re.compile(
    rf"\b(?:tầm|khoảng|tam|khoang|cỡ|co)\s*(?:khoảng\s*)?(\d+(?:[.,]\d+)?)\s*({BUDGET_UNIT_ALTERNATION})\b",
    re.IGNORECASE,
)
_BARE_AREA_PATTERN = re.compile(r"\b(\d+(?:[.,]\d+)?)\s*m(?:2|²)\b", re.IGNORECASE)

_VAGUE_CHEAPER_PATTERN = re.compile(r"\b(giá mềm|gia mem|rẻ hơn|re hon|rẻ chút|giá tốt hơn|mềm hơn)\b", re.IGNORECASE)
_VAGUE_BIGGER_PATTERN = re.compile(r"\b(rộng hơn|rong hon|rộng chút|rộng một chút|to hơn|lớn hơn)\b", re.IGNORECASE)
_VAGUE_SMALLER_PATTERN = re.compile(r"\b(nhỏ hơn|nho hon|gọn hơn|nhỏ chút)\b", re.IGNORECASE)
_MOVE_IN_NOW_PATTERN = re.compile(r"\b(ở được ngay|o duoc ngay|vào ở ngay|vao o ngay|nhận nhà ngay)\b", re.IGNORECASE)
_HOUSEHOLD_PATTERN = re.compile(r"\b(?:gia đình|nhà|hộ|cho)\s*(\d+)\s*(?:người|nguoi|thành viên)\b", re.IGNORECASE)

_PURPOSE_PATTERNS = (
    (
        re.compile(r"\b(để ở|mua ở|vừa ở|an cư|dinh cư|định cư|de o|mua o|vua o|an cu|dinh cu)\b", re.IGNORECASE),
        "living",
    ),
    (
        re.compile(
            r"\b(đầu tư|dau tu|cho thuê lại|cho thue lai|mua\s+(?:để\s+)?tăng giá|mua\s+(?:de\s+)?tang gia)\b",
            re.IGNORECASE,
        ),
        "investment",
    ),
    (re.compile(r"\b(kinh doanh|văn phòng|van phong|mở cửa hàng|mo cua hang)\b", re.IGNORECASE), "business"),
)

_SORT_PATTERNS = (
    (re.compile(r"\b(giá thấp đến cao|rẻ nhất|gia thap den cao|re nhat)\b", re.IGNORECASE), "price_asc"),
    (re.compile(r"\b(giá cao đến thấp|đắt nhất|gia cao den thap|dat nhat)\b", re.IGNORECASE), "price_desc"),
    (re.compile(r"\b(diện tích lớn nhất|rộng nhất|dien tich lon nhat|rong nhat)\b", re.IGNORECASE), "area_desc"),
    (
        re.compile(
            r"\b(giá trên m(?:2|²) thấp nhất|đơn giá thấp nhất|gia tren m(?:2|2) thap nhat|don gia thap nhat)\b",
            re.IGNORECASE,
        ),
        "price_per_m2_asc",
    ),
    (re.compile(r"\b(mới đăng|moi dang)\b", re.IGNORECASE), "listed_at_desc"),
    (re.compile(r"\b(gần nhất|gan nhat)\b", re.IGNORECASE), "distance_asc"),
    (re.compile(r"\b(phù hợp nhất|phu hop nhat)\b", re.IGNORECASE), "best_match"),
    (re.compile(r"\b(được quan tâm nhiều nhất|duoc quan tam nhieu nhat)\b", re.IGNORECASE), "popularity_desc"),
    (re.compile(r"\b(vào ở sớm nhất|vao o som nhat)\b", re.IGNORECASE), "move_in_asc"),
    (re.compile(r"\b(pháp lý đầy đủ trước|phap ly day du truoc)\b", re.IGNORECASE), "legal_first"),
    (re.compile(r"\b(nhà mới trước|nha moi truoc)\b", re.IGNORECASE), "property_age_asc"),
    (re.compile(r"\b(tiềm năng đầu tư tốt nhất|tiem nang dau tu tot nhat)\b", re.IGNORECASE), "investment_desc"),
    (re.compile(r"\b(chi phí tổng thấp nhất|chi phi tong thap nhat)\b", re.IGNORECASE), "total_cost_asc"),
)

_VAGUE_PRICE_TOLERANCE = 0.15
_CHEAPER_FACTOR = 0.8
_BIGGER_FACTOR = 1.15

_FEATURE_WORDS = (
    "hồ bơi",
    "bể bơi",
    "gym",
    "phòng gym",
    "công viên",
    "sân chơi",
    "trường học",
    "siêu thị",
    "ban công",
    "sân vườn",
    "thang máy",
    "chỗ đỗ ô tô",
    "chỗ để xe",
    "hầm để xe",
    "nội thất",
    "view sông",
    "view biển",
    "view thành phố",
    "an ninh",
    "yên tĩnh",
    "nhiều cây xanh",
    "ít tiếng ồn",
    "không bị ngập",
    "bảo vệ 24/7",
    "camera",
    "phòng cháy chữa cháy",
    "trạm sạc xe điện",
    "khu BBQ",
    "đường chạy bộ",
    "thú cưng",
    "gần bệnh viện",
    "gần trung tâm thương mại",
    "gần metro",
    "gần trạm xe buýt",
    "phòng thờ",
    "phòng kho",
    "phòng giặt",
    "phòng giúp việc",
    "sân thượng",
    "sân trước",
    "sân sau",
    "gara",
    "tầng hầm",
    "gác lửng",
    "đầy đủ nội thất",
    "nội thất cơ bản",
    "nhà trống",
    "điều hòa",
    "máy giặt",
    "tủ lạnh",
    "ánh sáng tự nhiên",
    "thông gió tự nhiên",
    "người lớn tuổi",
    "trẻ nhỏ",
    "người khuyết tật",
)

_VIEW_FEATURE_PATTERN = re.compile(r"\bview(?:\s+[^\W\d_]+)?\b", re.IGNORECASE)


def parse_criteria(query: str, known_subdivisions: list[str] | None = None) -> CriteriaDelta:
    """Turn one question into a delta against whatever criteria already exist.

    `known_subdivisions` comes from the fetched inventory: subdivision names are project
    data, not something a pattern can know in advance — the same approach
    inventory_service._extract_subdivision already takes, just with the candidate list
    passed in rather than derived from the units being filtered.
    """
    if not query or not query.strip():
        return CriteriaDelta()

    if _RESET_PATTERN.search(query):
        return CriteriaDelta(intent=Intent.RESET)
    if _UNDO_PATTERN.search(query):
        return CriteriaDelta(intent=Intent.UNDO)

    mandatory = bool(_MANDATORY_PATTERN.search(query))
    constraints: list[Constraint] = []
    unresolved: list[str] = []

    type_mentions = _inv._extract_unit_type_mentions(query)
    included_types = [item for item, excluded in type_mentions if not excluded]
    excluded_types = [item for item, excluded in type_mentions if excluded]
    if included_types:
        constraints.append(Constraint(FIELD_UNIT_TYPES, included_types, Strength.HARD, Source.EXPLICIT))
    if excluded_types:
        constraints.append(Constraint(FIELD_UNIT_TYPES, excluded_types, Strength.EXCLUDED, Source.EXPLICIT))

    unit_code = _inv._extract_unit_code(query)
    if unit_code is not None:
        constraints.append(Constraint(FIELD_UNIT_CODES, [unit_code], Strength.HARD, Source.EXPLICIT))

    price_range = _inv._extract_price_range(query)
    if price_range is not None:
        constraints.append(Constraint(FIELD_PRICE, price_range, Strength.HARD, Source.EXPLICIT))
    else:
        adjusted_price = _parse_price_adjustment(query)
        if adjusted_price is not None:
            constraints.append(Constraint(FIELD_PRICE, adjusted_price, Strength.HARD, Source.EXPLICIT))
        else:
            vague_price = _parse_vague_price(query)
            if vague_price is not None:
                constraints.append(Constraint(FIELD_PRICE, vague_price, Strength.HARD, Source.INFERRED))
            elif _VAGUE_CHEAPER_PATTERN.search(query):
                unresolved.append("giá")

    area_range = _inv._extract_area_range(query) or _parse_area_adjustment(query)
    area_source = Source.EXPLICIT
    if area_range is None:
        bare = _BARE_AREA_PATTERN.search(query)
        if bare is not None:
            area_range = (_inv._to_number(bare.group(1)), float("inf"))
            area_source = Source.INFERRED

    if area_range is not None:
        strength = Strength.HARD if mandatory else Strength.SOFT
        constraints.append(Constraint(FIELD_AREA, area_range, strength, area_source))
    elif _VAGUE_BIGGER_PATTERN.search(query) or _VAGUE_SMALLER_PATTERN.search(query):
        unresolved.append("diện tích")

    status = _inv._extract_status(query)
    if status is not None:
        constraints.append(Constraint(FIELD_STATUSES, [status], Strength.HARD, Source.EXPLICIT))
    elif _MOVE_IN_NOW_PATTERN.search(query):
        constraints.append(Constraint(FIELD_STATUSES, ["available"], Strength.HARD, Source.INFERRED))

    direction = _inv._extract_direction(query)
    if direction is not None:
        constraints.append(
            Constraint(
                FIELD_DIRECTIONS,
                [direction],
                Strength.HARD if mandatory else Strength.SOFT,
                Source.EXPLICIT,
            )
        )

    views = _inv._extract_view_types(query)
    if views:
        constraints.append(
            Constraint(
                FIELD_VIEWS,
                views,
                Strength.HARD if mandatory else Strength.SOFT,
                Source.EXPLICIT,
            )
        )

    tower = _inv._extract_tower(query)
    if tower is not None:
        constraints.append(Constraint(FIELD_TOWERS, [tower], Strength.HARD, Source.EXPLICIT))

    floor = _inv._extract_floor(query)
    if floor is not None:
        constraints.append(Constraint(FIELD_FLOORS, [floor], Strength.HARD, Source.EXPLICIT))

    subdivision = _match_subdivision(query, known_subdivisions or [])
    if subdivision is not None:
        if _is_excluded_subdivision(query, subdivision):
            strength = Strength.EXCLUDED
        else:
            strength = Strength.HARD if mandatory else Strength.SOFT
        constraints.append(Constraint(FIELD_SUBDIVISIONS, [subdivision], strength, Source.EXPLICIT))

    features = _extract_features(query)
    household = _extract_household(query)
    purpose = _extract_purpose(query)
    sort_by = _extract_sort(query)

    if _DROP_PATTERN.search(query):
        dropped = _resolve_dropped(query, features, constraints)
        if dropped:
            return CriteriaDelta(intent=Intent.DROP, dropped_fields=dropped)

    excluded = bool(_EXCLUDE_PATTERN.search(query))
    if excluded:
        constraints = [
            item if item.field == FIELD_UNIT_TYPES else replace(item, strength=Strength.EXCLUDED)
            for item in constraints
        ]

    return CriteriaDelta(
        intent=Intent.REFINE,
        constraints=tuple(constraints),
        required_features=tuple(features) if mandatory and not excluded else (),
        preferred_features=tuple(features) if not mandatory and not excluded else (),
        excluded_features=tuple(features) if excluded else (),
        household_size=household,
        purpose=purpose,
        sort_by=sort_by,
        unresolved_vague=tuple(unresolved),
    )


def _parse_price_adjustment(query: str) -> tuple[float, float] | None:
    """ "tăng giá lên 5 tỷ" / "giảm xuống 3 tỷ" -> a new ceiling of 5 tỷ / 3 tỷ.

    Both directions produce a ceiling, never a floor: raising the limit still keeps
    everything cheaper in play. The lower bound is preserved by `merge_criteria`, not
    invented here.
    """
    match = _RAISE_PATTERN.search(query) or _LOWER_PATTERN.search(query)
    if match is None:
        return None
    ceiling = parse_vnd(match.group(1), match.group(2), profile=Profile.CONVERSATIONAL)
    if ceiling is None:
        return None
    return 0.0, float(ceiling)


def _parse_area_adjustment(query: str) -> tuple[float, float] | None:
    """ "tăng diện tích lên 80m2" -> a floor of 80m².

    The mirror image of price: raising an area target means "at least this big", because
    area is something a person wants more of while price is something they want less of.
    """
    match = _AREA_ADJUST_PATTERN.search(query)
    if match is None:
        return None
    return _inv._to_number(match.group(1)), float("inf")


def _parse_vague_price(query: str) -> tuple[float, float] | None:
    """ "tầm 3 tỷ" -> a band around 3 tỷ. None when no such phrase appears."""
    match = _VAGUE_AROUND_PATTERN.search(query)
    if match is None:
        return None
    centre = parse_vnd(match.group(1), match.group(2), profile=Profile.CONVERSATIONAL)
    if centre is None:
        return None
    return round(centre * (1 - _VAGUE_PRICE_TOLERANCE)), round(centre * (1 + _VAGUE_PRICE_TOLERANCE))


def _match_subdivision(query: str, known: list[str]) -> str | None:
    """Longest known subdivision name/short alias appearing in the question."""
    normalized_query = _inv._normalize_text(query)
    matches = [
        name for name in known if name and any(alias in normalized_query for alias in _subdivision_aliases(name))
    ]
    return max(matches, key=len) if matches else None


def _subdivision_aliases(name: str) -> tuple[str, ...]:
    normalized = _inv._normalize_text(name)
    short = normalized.removeprefix("the ")
    return tuple(dict.fromkeys(alias for alias in (normalized, short) if alias))


def _is_excluded_subdivision(query: str, name: str) -> bool:
    """Whether the local phrase rejects this subdivision rather than selecting it."""
    normalized_query = _inv._normalize_text(query)
    occurrences = [normalized_query.find(alias) for alias in _subdivision_aliases(name) if alias in normalized_query]
    if not occurrences:
        return False
    position = min(occurrences)
    prefix = normalized_query[max(0, position - 60) : position]
    return _LOCATION_EXCLUDE_PREFIX.search(prefix) is not None


def _extract_features(query: str) -> list[str]:
    normalized = _inv._normalize_text(query)
    features = [word for word in _FEATURE_WORDS if _inv._normalize_text(word) in normalized]
    if not _inv._extract_view_types(query):
        features.extend(match.group(0) for match in _VIEW_FEATURE_PATTERN.finditer(query))
    return list(dict.fromkeys(features))


def _extract_household(query: str) -> int | None:
    match = _HOUSEHOLD_PATTERN.search(query)
    if match is None:
        return None
    size = int(match.group(1))
    return size if 1 <= size <= 12 else None


def _extract_purpose(query: str) -> str | None:
    purposes = [purpose for pattern, purpose in _PURPOSE_PATTERNS if pattern.search(query)]
    return "+".join(purposes) if purposes else None


def _extract_sort(query: str) -> str | None:
    for pattern, sort_by in _SORT_PATTERNS:
        if pattern.search(query):
            return sort_by
    return None


def _resolve_dropped(query: str, features: list[str], constraints: list[Constraint]) -> tuple[str, ...]:
    """Which criterion "bỏ yêu cầu X" refers to.

    Features are named directly ("bỏ yêu cầu hồ bơi"); a constraint is named by the field
    the sentence mentions ("bỏ yêu cầu 3PN" parses a unit type, so drop unit_types).
    """
    dropped: list[str] = [f"feature:{name}" for name in features]
    dropped.extend(constraint.field for constraint in constraints)
    if dropped:
        return tuple(dropped)

    normalized = _inv._normalize_text(query)
    for keyword, field_name in (
        ("gia", FIELD_PRICE),
        ("dien tich", FIELD_AREA),
        ("phan khu", FIELD_SUBDIVISIONS),
        ("loai can", FIELD_UNIT_TYPES),
    ):
        if keyword in normalized:
            return (field_name,)
    return ()


def merge_criteria(previous: SearchCriteria, delta: CriteriaDelta) -> SearchCriteria:
    """Fold one turn's delta into what came before.

    Merge, never replace, is the whole point: "tăng giá lên 5 tỷ" mentions no unit type, so
    a previously stated 3PN must survive. Replacing is what the stateless path already
    does, and what makes a consultation restart from nothing every turn.

    UNDO is not handled here — it needs the stored history stack, so `resolve` does it.
    """
    if delta.intent == Intent.RESET:
        return SearchCriteria()

    if delta.intent == Intent.DROP:
        return _drop_fields(previous, delta.dropped_fields)

    constraints = list(previous.constraints)
    for incoming in delta.constraints:
        constraints = [
            existing
            for existing in constraints
            if not (existing.field == incoming.field and existing.strength == incoming.strength)
        ]
        constraints.append(incoming)

    constraints = _resolve_relative(constraints, delta)

    return SearchCriteria(
        constraints=tuple(constraints),
        required_features=_merge_features(previous.required_features, delta.required_features),
        preferred_features=_merge_features(previous.preferred_features, delta.preferred_features),
        excluded_features=_merge_features(previous.excluded_features, delta.excluded_features),
        purpose=delta.purpose if delta.purpose is not None else previous.purpose,
        household_size=delta.household_size if delta.household_size is not None else previous.household_size,
        sort_by=delta.sort_by if delta.sort_by is not None else previous.sort_by,
    )


def _resolve_relative(constraints: list[Constraint], delta: CriteriaDelta) -> list[Constraint]:
    """Apply "rẻ hơn"/"rộng hơn" to the bound already in place, when there is one."""
    if "giá" in delta.unresolved_vague:
        existing = next((c for c in constraints if c.field == FIELD_PRICE), None)
        if existing is not None:
            minimum, maximum = existing.value
            constraints = [c for c in constraints if c.field != FIELD_PRICE]
            constraints.append(
                Constraint(FIELD_PRICE, (minimum, round(maximum * _CHEAPER_FACTOR)), existing.strength, Source.INFERRED)
            )

    if "diện tích" in delta.unresolved_vague:
        existing = next((c for c in constraints if c.field == FIELD_AREA), None)
        if existing is not None:
            minimum, maximum = existing.value
            constraints = [c for c in constraints if c.field != FIELD_AREA]
            constraints.append(
                Constraint(
                    FIELD_AREA, (round(minimum * _BIGGER_FACTOR, 1), maximum), existing.strength, Source.INFERRED
                )
            )

    return constraints


def _drop_fields(criteria: SearchCriteria, dropped: tuple[str, ...]) -> SearchCriteria:
    feature_names = {name[len("feature:") :] for name in dropped if name.startswith("feature:")}
    field_names = {name for name in dropped if not name.startswith("feature:")}

    return replace(
        criteria,
        constraints=tuple(c for c in criteria.constraints if c.field not in field_names),
        required_features=tuple(f for f in criteria.required_features if f not in feature_names),
        preferred_features=tuple(f for f in criteria.preferred_features if f not in feature_names),
    )


def _merge_features(existing: tuple[str, ...], incoming: tuple[str, ...]) -> tuple[str, ...]:
    merged = list(existing)
    for item in incoming:
        if item not in merged:
            merged.append(item)
    return tuple(merged)


def detect_conflict(criteria: SearchCriteria) -> str | None:
    """A Vietnamese sentence naming the contradiction, or None when there is none.

    Only impossible combinations count, never merely narrow ones — a false alarm costs a
    whole turn on a search that would have worked. "trung tâm + yên tĩnh + giá thấp" is a
    trade-off the answer should discuss, not a contradiction to block on.
    """
    price = criteria.get(FIELD_PRICE)
    if price is not None:
        minimum, maximum = price.value
        if minimum > maximum:
            return (
                f"Anh/chị đang đặt giá tối thiểu {_format_price(minimum)} cao hơn giá tối đa "
                f"{_format_price(maximum)}. Anh/chị muốn ưu tiên mức nào ạ?"
            )

    area = criteria.get(FIELD_AREA)
    if area is not None:
        minimum, maximum = area.value
        if minimum > maximum:
            return (
                f"Diện tích tối thiểu {_format_area(minimum)} đang lớn hơn diện tích tối đa "
                f"{_format_area(maximum)}. Anh/chị muốn ưu tiên mức nào ạ?"
            )

    unit_types = criteria.get(FIELD_UNIT_TYPES)
    if unit_types is not None and area is not None:
        bedrooms = _bedroom_count(unit_types.value)
        _, area_max = area.value
        if bedrooms is not None and area_max != float("inf") and area_max < bedrooms * 25:
            return (
                f"Căn {bedrooms}PN thường không có diện tích dưới {_format_area(area_max)}. "
                "Anh/chị muốn ưu tiên số phòng ngủ hay diện tích ạ?"
            )

    return None


def _bedroom_count(unit_types: list[str]) -> int | None:
    for unit_type in unit_types:
        match = re.fullmatch(r"(?:MIN|MAX)?(\d+)PN\+?", str(unit_type).upper())
        if match:
            return int(match.group(1))
    return None


def _display_unit_type(value: str) -> str:
    text = str(value)
    minimum = re.fullmatch(r"MIN(\d+PN\+?)", text, re.IGNORECASE)
    maximum = re.fullmatch(r"MAX(\d+PN\+?)", text, re.IGNORECASE)
    if minimum:
        return f"từ {minimum.group(1)}"
    if maximum:
        return f"tối đa {maximum.group(1)}"
    labels = {
        "CANHO": "căn hộ/chung cư",
        "BIETTHU": "biệt thự",
        "BT_DL": "biệt thự đơn lập",
        "BT_SL": "biệt thự song lập",
        "LK": "nhà liền kề/nhà phố",
        "SH": "shophouse",
        "NHARIENG": "nhà riêng",
        "NHAHEM": "nhà trong hẻm/ngõ",
        "NHAMATTIEN": "nhà mặt tiền",
        "NHACAP4": "nhà cấp 4",
        "PHONGTRO": "phòng trọ",
        "NHANGUYENCAN": "nhà nguyên căn",
        "DATNEN": "đất nền",
        "DATTHOCU": "đất thổ cư",
        "DATDUAN": "đất dự án",
        "NHAVUON": "trang trại/nhà vườn",
        "KHOXUONG": "kho/xưởng",
        "VANPHONG": "văn phòng",
        "MATBANG": "mặt bằng kinh doanh",
        "NGHIDUONG": "bất động sản nghỉ dưỡng",
    }
    return labels.get(text.upper(), text)


def format_criteria(criteria: SearchCriteria) -> str:
    """Render for the prompt, grouped by strength. Empty criteria render as ""."""
    if criteria.is_empty():
        return ""

    lines: list[str] = []

    hard = [c.describe() for c in criteria.constraints if c.strength == Strength.HARD]
    hard.extend(criteria.required_features)
    if hard:
        lines.append(f"- Bắt buộc: {'; '.join(hard)}")

    soft = [c.describe() for c in criteria.constraints if c.strength == Strength.SOFT]
    soft.extend(criteria.preferred_features)
    if soft:
        lines.append(f"- Ưu tiên: {'; '.join(soft)}")

    excluded = [c.describe() for c in criteria.constraints if c.strength == Strength.EXCLUDED]
    excluded.extend(criteria.excluded_features)
    if excluded:
        lines.append(f"- Loại trừ: {'; '.join(excluded)}")

    if criteria.household_size:
        lines.append(f"- Số người ở: {criteria.household_size}")

    if criteria.purpose:
        labels = {"living": "để ở", "investment": "đầu tư", "business": "kinh doanh"}
        lines.append(f"- Mục đích: {labels.get(criteria.purpose, criteria.purpose)}")

    if criteria.sort_by:
        labels = {
            "price_asc": "giá thấp đến cao",
            "price_desc": "giá cao đến thấp",
            "area_desc": "diện tích lớn nhất trước",
            "price_per_m2_asc": "đơn giá/m² thấp nhất trước",
        }
        lines.append(f"- Sắp xếp: {labels.get(criteria.sort_by, criteria.sort_by)}")

    return "\n".join(lines)


def diagnose_zero_results(units: list[Any], criteria: SearchCriteria) -> ZeroResultDiagnosis | None:
    """Find the smallest active constraint set whose removal restores results.

    The returned counts are computed from the same in-memory inventory used for the real
    lookup. They are therefore grounding, not model estimates. We try one removal first;
    only when no single condition is sufficient do we try pairs.
    """
    from backend.services.inventory_service import apply_criteria

    active = criteria.filtering()
    if not units or not active or apply_criteria(list(units), criteria):
        return None

    options: list[RelaxOption] = []
    for constraint in active:
        remaining = tuple(item for item in criteria.constraints if item is not constraint)
        count = len(apply_criteria(list(units), replace(criteria, constraints=remaining)))
        if count:
            options.append(RelaxOption((constraint,), count))

    if not options and len(active) <= MAX_DIAGNOSIS_CONSTRAINTS:
        for pair in combinations(active, 2):
            pair_ids = {id(item) for item in pair}
            remaining = tuple(item for item in criteria.constraints if id(item) not in pair_ids)
            count = len(apply_criteria(list(units), replace(criteria, constraints=remaining)))
            if count:
                options.append(RelaxOption(pair, count))

    def priority(option: RelaxOption) -> tuple[int, int, int, int]:
        inferred = all(item.source == Source.INFERRED for item in option.removed)
        soft = all(item.strength == Strength.SOFT for item in option.removed)
        return (0 if soft else 1, 0 if inferred else 1, len(option.removed), -option.estimated_count)

    options.sort(key=priority)
    return ZeroResultDiagnosis(len(units), active, tuple(options))


def format_zero_result(diagnosis: ZeroResultDiagnosis) -> str:
    """Render diagnosis as grounded facts and strict generation instructions."""
    lines = [
        f"- Tổng tồn kho trước lọc: {diagnosis.total_units} căn.",
        "- Không có căn nào đồng thời thỏa tất cả tiêu chí đang áp dụng.",
    ]
    for option in diagnosis.relax_options:
        removed = " + ".join(item.describe() for item in option.removed)
        lines.append(f"- Nếu nới/bỏ {removed}: có {option.estimated_count} căn.")
    lines.append(
        "BẮT BUỘC: nêu đúng tiêu chí gây rỗng và đúng số đếm trên; chỉ đề xuất nới MỘT "
        "phương án ít quan trọng nhất, không tự tuyên bố đã bỏ tiêu chí và không trả lời chung chung."
    )
    return "\n".join(lines)


def format_diagnosis_for_verifier(diagnosis: ZeroResultDiagnosis) -> str:
    """The same computed facts in a neutral form the Verifier can check against."""
    return "Zero-result inventory diagnosis:\n" + format_zero_result(diagnosis)


def _describe_range(value: tuple[float, float], formatter) -> str:
    minimum, maximum = value
    if minimum <= 0 and maximum != float("inf"):
        return f"tối đa {formatter(maximum)}"
    if maximum == float("inf"):
        return f"từ {formatter(minimum)}"
    return f"{formatter(minimum)} - {formatter(maximum)}"


def _format_price(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.3g} tỷ"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.3g} triệu"
    return f"{value:.0f}"


def _format_area(value: float) -> str:
    return f"{value:.4g}m²"


def load(session_id: int) -> tuple[SearchCriteria, list[SearchCriteria]]:
    """Read a session's criteria and undo stack. Any failure yields empty, never raises."""
    client = get_redis_client()
    if client is None or not get_settings().search_criteria_enabled:
        return SearchCriteria(), []

    try:
        raw = client.get(session_key(session_id))
    except Exception:
        logger.warning(
            "Doc tieu chi tim kiem that bai; coi nhu chua co tieu chi.",
            exc_info=True,
            extra={"event": "criteria.load.failed", "session_id": session_id},
        )
        return SearchCriteria(), []

    if not raw:
        return SearchCriteria(), []

    try:
        data = json.loads(raw)
        current = _from_dict(data.get("current") or {})
        history = [_from_dict(item) for item in (data.get("history") or [])]
        return current, history
    except (ValueError, TypeError, KeyError):
        logger.warning(
            "Tieu chi tim kiem hong; bo qua.",
            extra={"event": "criteria.load.corrupt", "session_id": session_id},
        )
        return SearchCriteria(), []


def save(session_id: int, current: SearchCriteria, history: list[SearchCriteria]) -> None:
    """Persist criteria plus undo stack. Never raises — a failed write costs nothing the
    person sees this turn, since the answer being served is already complete."""
    client = get_redis_client()
    if client is None or not get_settings().search_criteria_enabled:
        return

    try:
        client.set(
            session_key(session_id),
            json.dumps(
                {
                    "current": _to_dict(current),
                    "history": [_to_dict(item) for item in history[:MAX_HISTORY_SNAPSHOTS]],
                },
                ensure_ascii=False,
            ),
            ex=get_settings().search_criteria_ttl_seconds,
        )
    except Exception:
        logger.warning(
            "Ghi tieu chi tim kiem that bai; cau tra loi khong bi anh huong.",
            exc_info=True,
            extra={"event": "criteria.save.failed", "session_id": session_id},
        )


def clear(session_id: int) -> None:
    client = get_redis_client()
    if client is None:
        return
    try:
        client.delete(session_key(session_id))
    except Exception:
        logger.warning(
            "Xoa tieu chi tim kiem that bai.",
            exc_info=True,
            extra={"event": "criteria.clear.failed", "session_id": session_id},
        )


def resolve(
    session_id: int | None, query: str, known_subdivisions: list[str] | None = None
) -> tuple[SearchCriteria, CriteriaDelta]:
    """Load, merge this turn, persist, and hand back the result.

    `session_id is None` is the fail-open path, not an error: criteria are simply switched
    off. Nothing contradictory is persisted, so the stored state stays at the last
    coherent version.
    """
    delta = parse_criteria(query, known_subdivisions)

    if session_id is None:
        return merge_criteria(SearchCriteria(), delta), delta

    previous, history = load(session_id)

    if delta.intent == Intent.UNDO:
        if not history:
            return previous, delta
        restored, *rest = history
        save(session_id, restored, rest)
        return restored, delta

    merged = merge_criteria(previous, delta)

    if merged == previous:
        return merged, delta

    if detect_conflict(merged) is None:
        snapshots = [previous, *history] if not previous.is_empty() else list(history)
        save(session_id, merged, snapshots[:MAX_HISTORY_SNAPSHOTS])

    return merged, delta


def _to_dict(criteria: SearchCriteria) -> dict:
    return {
        "constraints": [
            {
                "field": c.field,
                "value": _encode_value(c.value),
                "strength": str(c.strength),
                "source": str(c.source),
            }
            for c in criteria.constraints
        ],
        "required_features": list(criteria.required_features),
        "preferred_features": list(criteria.preferred_features),
        "excluded_features": list(criteria.excluded_features),
        "purpose": criteria.purpose,
        "household_size": criteria.household_size,
        "sort_by": criteria.sort_by,
    }


def _encode_value(value: Any) -> Any:
    """Ranges become 2-element lists, with `inf` as null.

    `json.dumps` writes bare `Infinity` for a float infinity — valid to Python's loader but
    not to redis-cli or a dashboard. An open-ended bound from "trên 3 tỷ" makes this a real
    round-trip.
    """
    if isinstance(value, tuple):
        return [None if v == float("inf") else v for v in value]
    return value


def _decode_value(value: Any) -> Any:
    if isinstance(value, list) and len(value) == 2 and all(v is None or isinstance(v, (int, float)) for v in value):
        return tuple(float("inf") if v is None else float(v) for v in value)
    return value


def _from_dict(data: dict) -> SearchCriteria:
    constraints: list[Constraint] = []
    for item in data.get("constraints") or []:
        value = _decode_value(item["value"])
        constraints.append(
            Constraint(
                field=item["field"],
                value=value,
                strength=Strength(item.get("strength", Strength.HARD)),
                source=Source(item.get("source", Source.EXPLICIT)),
            )
        )

    return SearchCriteria(
        constraints=tuple(constraints),
        required_features=tuple(data.get("required_features") or []),
        preferred_features=tuple(data.get("preferred_features") or []),
        excluded_features=tuple(data.get("excluded_features") or []),
        purpose=data.get("purpose"),
        household_size=data.get("household_size"),
        sort_by=data.get("sort_by"),
    )
