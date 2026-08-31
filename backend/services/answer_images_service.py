"""Image tool: attach the project photos that illustrate an answer.

Two routes with opposite postures. **Requested** ("cho xem mặt bằng") returns every
matching photo uncapped and falls back to the whole gallery — refusing someone who asked
to see something is the worse failure. **Automatic** (photos riding along an answer nobody
asked to illustrate) is capped at `_AUTO_ATTACH_MAX_IMAGES` and returns nothing on no
match — an unasked-for photo of the wrong thing is worse than no photo.

Both require the project to be named and the filename to carry the topic, which is what
makes per-image relevance possible instead of dumping the gallery.
"""

import logging
import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.core.config import settings
from backend.core.minio_client import public_object_url
from backend.models.project import Project
from backend.utils.text import strip_diacritics

logger = logging.getLogger(__name__)


def public_gallery_url(value: str) -> str:
    """Normalise a gallery entry into a URL a browser can load.

    Entries are either a full external URL (PROJECT_IMAGES_BASE_URL was set at load time)
    or a bare MinIO object key with a stray leading slash. The object exists either way,
    so the fix is building the URL, not re-uploading.
    """
    if value.startswith("http://") or value.startswith("https://"):
        return value
    return public_object_url(settings.minio_bucket_project_images, value.lstrip("/"))


_SHARED_NONDISTINGUISHING_PHOTO_PATTERN = re.compile(r"santan?-monica")


def _drop_shared_nondistinguishing_photos(gallery: list[str]) -> list[str]:
    return [url for url in gallery if not _SHARED_NONDISTINGUISHING_PHOTO_PATTERN.search(url.lower())]


_MIN_NAME_LENGTH = 4

_AUTO_ATTACH_MAX_IMAGES = 3


@dataclass(frozen=True)
class ProjectReferences:
    """Catalogue projects named positively and negatively in one utterance."""

    included_ids: tuple[str, ...] = ()
    excluded_ids: tuple[str, ...] = ()


_OVERVIEW_TOKENS = ("phoi-canh", "tong-the", "toan-canh", "3d-", "mat-ngoai")

_IMAGE_INTENT_KEYWORDS = (
    "hinh anh",
    "hinh",
    "xem anh",
    "coi anh",
    "buc anh",
    "tam anh",
    "cac anh",
    "toi anh",
    "em anh",
    "minh anh",
    "photo",
    "image",
    "mat bang",
    "phoi canh",
    "so do",
    "ban ve",
    "layout",
    "mat cat",
    "thiet ke",
    "gallery",
    "thu vien anh",
)

_LOOK_VERBS = ("xem", "coi", "show")

_CATEGORY_FOLDERS = frozenset({"tien-ich", "mat-bang", "hinh-anh-thuc-te"})

_TOPIC_TOKENS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("mat bang", "layout", "so do", "ban ve", "mat cat"), ("mat-bang", "matbang")),
    (("tien ich",), ("tien-ich", "tienich", "phong-")),
    (("vi tri", "ket noi", "lien ket", "ban do"), ("vi-tri", "ket-noi", "lien-ket", "vitri")),
    (("phoi canh", "toan canh", "tong the"), ("phoi-canh", "tong-the", "toan-canh")),
    (("biet thu",), ("biet-thu", "bietthu")),
    (("shophouse", "shop", "thuong mai"), ("shop", "thuong-mai")),
    (("can ho", "chung cu"), ("can-ho", "chung-cu")),
    (("be boi", "ho boi"), ("be-boi", "ho-boi")),
    (("ho",), ("ho-dieu-hoa", "ho-canh-quan", "ho-ngoc-trai", "bien-ho")),
    (("bien",), ("bien-ho", "bien-")),
    (("cong vien", "canh quan"), ("cong-vien", "canh-quan")),
    (("view", "tam nhin", "huong nhin", "huong can"), ("view-", "tam-nhin", "huong-nhin")),
    (("noi that",), ("noi-that", "noithat")),
    (("phan khu",), ("phan-khu", "phankhu")),
    (("toa", "tower"), ("toa-", "toa")),
)


def wants_images(query: str) -> bool:
    """True when the question asks to see something, not merely to know something.

    Diacritic-insensitive: "cho xem mat bang" is as common as "cho xem mặt bằng".
    """
    normalized = _normalize(query)
    if _contains_phrase(normalized, _IMAGE_INTENT_KEYWORDS):
        return True

    return _contains_phrase(normalized, _LOOK_VERBS) and bool(_subject_tokens(normalized))


def collect_images(db: Session, query: str, answer: str, project_id: str | None = None) -> list[dict]:
    """Photos to show under this answer — those asked for, or those that illustrate it.

    Takes whichever of the module docstring's two routes `wants_images` selects. Reads the
    project name from question *and* answer, because "cho xem mặt bằng" often names no
    project and the name only appears in the grounded answer.

    Never raises: images are a nice-to-have and must not cost the Sale their answer.
    """
    try:
        haystack = _normalize(f"{query}\n{answer}")
        if not haystack.strip():
            return []

        if project_id is None and not wants_images(query) and len(resolve_project_ids(db, haystack)) > 1:
            return []

        references = resolve_project_references(db, query)
        excluded_ids = set(references.excluded_ids)
        project = db.get(Project, project_id) if project_id else _best_match(db, haystack)
        if project is not None and project.id in excluded_ids:
            return []
        if project is None:
            return _images_from_category(db, _normalize(query))

        details: dict = project.details or {}
        overview_towers = ((details.get("project") or {}).get("overview") or {}).get("towers") or []
        known_towers = overview_towers if isinstance(overview_towers, list) else []
        images: dict = details.get("images") or {}
        gallery = _drop_shared_nondistinguishing_photos(
            [url for url in images.get("gallery") or [] if isinstance(url, str) and url]
        )
        if not gallery:
            return []

        normalized_query = _normalize(query)
        if wants_images(query):
            selected = _filter_by_topic(gallery, normalized_query, known_towers)
        else:
            selected = _auto_attach_images(gallery, normalized_query, known_towers)

        return [
            {"url": public_gallery_url(url), "project_id": project.id, "project_name": project.name} for url in selected
        ]
    except Exception:
        logger.exception(
            "Could not resolve answer images; answering without them.",
            extra={"event": "answer_images.failed"},
        )
        return []


_FLOORPLAN_SHEET_TOWER_PATTERN = re.compile(r"toa-([a-z]{1,5}\d+)")


def floor_plan_only_towers(db: Session, query: str, answer: str, project_id: str | None = None) -> list[str] | None:
    """Tower codes of the gallery's tower-wide floor-plan sheets, or None when it has real
    per-unit-type plans instead.

    Some catalogues (The London) were only digitised as one sheet per tower. Those are
    excluded from a "2PN" card, so without this the model cannot know that a bedroom-count
    follow-up has no photo while a tower-named one does — it lets `build_prompt` steer the
    suggestion toward the question that actually has an answer.
    """
    try:
        haystack = _normalize(f"{query}\n{answer}")
        project = db.get(Project, project_id) if project_id else _best_match(db, haystack)
        if project is None:
            return None

        gallery = [
            url for url in ((project.details or {}).get("images") or {}).get("gallery") or [] if isinstance(url, str)
        ]
        if not gallery or any(_UNIT_TYPE_PHOTO_PATTERN.search(_normalize_filename(url)) for url in gallery):
            return None

        towers: list[str] = []
        for url in gallery:
            name = _normalize_filename(url)
            if "mat-bang" not in name and "matbang" not in name:
                continue
            match = _FLOORPLAN_SHEET_TOWER_PATTERN.search(name)
            if match:
                towers.append(match.group(1).upper())
        return list(dict.fromkeys(towers))
    except Exception:
        logger.exception(
            "Could not resolve floor-plan tower availability; answering without the note.",
            extra={"event": "answer_images.floor_plan_towers.failed"},
        )
        return None


_CATEGORY_MATCH_TERMS: tuple[tuple[str, str], ...] = (
    ("biet thu", "Biệt thự"),
    ("chung cu", "Chung cư"),
    ("shophouse", "Shophouse"),
    ("shop tmdv", "Shophouse"),
    ("shop thuong mai", "Shophouse"),
)

_IMAGES_PER_CATEGORY_PROJECT = 2


def named_category(text: str) -> str | None:
    """The product category named in free text, spelled as `Project.details["pricing"]`
    spells it, or None.

    Lets `agent_pipeline._scope_resolve` tell a real topic switch ("biệt thự" while
    discussing an apartment project) from a follow-up on the same project.
    """
    normalized = _normalize(text)
    return next((label for phrase, label in _CATEGORY_MATCH_TERMS if phrase in normalized), None)


def project_categories(project: Project) -> set[str]:
    """Every product category this project's catalogue pricing sells — one for a sub-zone,
    several for the umbrella "Vinhomes Ocean Park" entry."""
    pricing = (project.details or {}).get("pricing") or []
    return {tier["category"] for tier in pricing if isinstance(tier, dict) and tier.get("category")}


def _images_from_category(db: Session, normalized_query: str) -> list[dict]:
    """A few photos from every project of the category named in the query ("ảnh biệt thự"),
    for when the question named a category rather than one project.

    A category word belongs to no project's alias set, so it can never resolve to a single
    project. Projects spanning multiple categories (the umbrella catalogue entry) are
    excluded: their overview shot would dominate every category's results.
    """
    category = next((label for phrase, label in _CATEGORY_MATCH_TERMS if phrase in normalized_query), None)
    if category is None:
        return []

    results: list[dict] = []
    for project in db.query(Project).all():
        pricing = (project.details or {}).get("pricing") or []
        categories = {tier["category"] for tier in pricing if tier.get("category")}
        if categories != {category}:
            continue

        gallery = _drop_shared_nondistinguishing_photos(
            [
                url
                for url in ((project.details or {}).get("images") or {}).get("gallery") or []
                if isinstance(url, str) and url
            ]
        )
        if not gallery:
            continue

        picked = _auto_attach_images(gallery, normalized_query, [])[:_IMAGES_PER_CATEGORY_PROJECT]
        results.extend(
            {"url": public_gallery_url(url), "project_id": project.id, "project_name": project.name} for url in picked
        )
    return results


def resolve_project_id(db: Session, text: str) -> str | None:
    """The catalogue id of the project named in `text`, or None.

    Sessions stopped carrying a `project_id` when the picker was dropped, so the question
    itself is the only place the project appears. Never raises: a caller that cannot
    identify the project simply remembers less.
    """
    try:
        references = resolve_project_references(db, text)
        return references.included_ids[0] if references.included_ids else None
    except Exception:
        logger.exception(
            "Could not resolve a project from text.",
            extra={"event": "answer_images.resolve_project.failed"},
        )
        return None


def resolve_project_ids(db: Session, text: str) -> list[str]:
    """Every catalogue project explicitly named in text, in mention order.

    Unlike `resolve_project_id`, this supports comparison questions that name two or more
    subdivisions. A parent project is suppressed when its only match is contained inside
    a longer matched catalogue name.
    """
    try:
        return list(resolve_project_references(db, text).included_ids)
    except Exception:
        logger.exception(
            "Could not resolve projects from text.",
            extra={"event": "answer_images.resolve_projects.failed"},
        )
        return []


def resolve_project_references(db: Session, text: str) -> ProjectReferences:
    """Split catalogue mentions into included and excluded projects.

    Name resolution alone cannot tell "Zenpark" from "ngoài Zenpark". Treating every
    mention as positive hard-scoped retrieval to the one project the customer had just
    rejected.
    """
    try:
        haystack = _normalize(text or "")
        if not haystack:
            return ProjectReferences()

        included: list[str] = []
        excluded: list[str] = []
        for position, _negative_length, project_id in _project_matches(db, haystack):
            target = excluded if _is_negative_reference(haystack, position) else included
            if project_id not in target:
                target.append(project_id)

        excluded_set = set(excluded)
        return ProjectReferences(
            included_ids=tuple(project_id for project_id in included if project_id not in excluded_set),
            excluded_ids=tuple(excluded),
        )
    except Exception:
        logger.exception(
            "Could not resolve positive/negative project references from text.",
            extra={"event": "answer_images.resolve_project_references.failed"},
        )
        return ProjectReferences()


def _project_matches(db: Session, haystack: str) -> list[tuple[int, int, str]]:
    matches: list[tuple[int, int, str]] = []
    for project in db.query(Project).all():
        candidates = _project_aliases(project)
        occurrences = [
            (match.start(), len(candidate))
            for candidate in candidates
            if len(candidate) >= _MIN_NAME_LENGTH
            for match in [re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", haystack)]
            if match is not None
        ]

        details = project.details or {}
        for tower in _known_project_towers(details):
            match = re.search(rf"(?<!\w){re.escape(tower)}(?!\w)", haystack)
            if match is not None:
                occurrences.append((match.start(), len(tower)))
        if occurrences:
            position, length = min(occurrences, key=lambda item: (item[0], -item[1]))
            matches.append((position, -length, project.id))

    grouped: dict[tuple[int, int], list[str]] = {}
    for position, negative_length, project_id in matches:
        grouped.setdefault((position, negative_length), []).append(project_id)
    matches = [item for item in matches if -item[1] >= _MIN_NAME_LENGTH or len(grouped[(item[0], item[1])]) == 1]
    matches.sort()
    return matches


_NEGATIVE_PROJECT_PREFIX = re.compile(
    r"(?:\bngoai\b(?!\s+ra\b)|\btru\b|\bkhong phai\b|\bkhong lay\b|\bkhong chon\b|"
    r"\bloai tru\b|\btranh\b|\bkhac voi\b)(?:\s+\w+){0,5}\s*$",
    re.IGNORECASE,
)


def _is_negative_reference(haystack: str, position: int) -> bool:
    prefix = haystack[max(0, position - 60) : position]
    return _NEGATIVE_PROJECT_PREFIX.search(prefix) is not None


_SUB_ZONE_NAME_PATTERN = re.compile(r"([a-z]+)\s+(\d+)$")


def _sub_zone_tokens(project_name: str) -> list[str]:
    """Filename tokens for a numbered sub-zone name ("The Sapphire 2" -> "sapphire-2").

    The Sapphire is the one project whose two sub-zones share a single row and gallery.
    Their only distinguishing photo is a per-sub-zone master plan, which the generic
    "mat-bang" exclusion would drop — leaving both cards showing identical park photos.
    """
    match = _SUB_ZONE_NAME_PATTERN.search(_normalize(project_name))
    if not match:
        return []
    word, number = match.groups()
    return [f"{word}-{number}", f"khu-{word}-{number}"]


_ZONE_OVERVIEW_UNIT_TYPE = "nhieu loai can"

_UNIT_TYPE_PHOTO_PATTERN = re.compile(
    r"(?:^|-)\d-?(?:ngu|pn|phong-ngu)(?:-?\+?1)?(?:-|$)|"
    r"(?:^|-)(?:studio|duplex|penthouse)(?:-|$)|"
    r"(?:^|-)(?:don-lap|song-lap|lien-ke)(?:-|$)"
)


def select_listing_images(
    gallery: list[str], unit_type: str, project_name: str = "", tower: str = "", unit_code: str = ""
) -> list[str]:
    """Pick photos to illustrate one recommended listing (agent_pipeline.PropertyListing).

    A live inventory card (`unit_code` present) gets `_inventory_listing_images`' fixed set
    describing that one unit, falling through to the catalogue route when it composes
    nothing — the villa zones file no photos under the catalogue folders it reads, and an
    empty card is worse than general photos of the right subdivision. A catalogue card gets
    photos of its unit type, else every non-floor-plan photo of the subdivision.

    Matches on `_unit_type_tokens` only, never the broader `_subject_tokens`: those include
    the generic "mat-bang" token, which would make a whole-tower floor plan match every
    unit type in that tower.

    Uncapped and unpadded — a type with two real photos shows exactly those.
    """
    if not gallery:
        return []

    gallery = _drop_shared_nondistinguishing_photos(gallery)
    if not gallery:
        return []

    if unit_code.strip():
        composed = _inventory_listing_images(gallery, unit_type, tower, unit_code)
        if composed:
            return composed

    tower_matches = _tower_photos(gallery, tower)
    if tower_matches:
        return tower_matches

    normalized_unit_type = _normalize(unit_type)
    unit_tokens = _unit_type_tokens(normalized_unit_type)
    type_matches = list(
        dict.fromkeys(url for url in gallery if _matches_any_filename_token(_normalize_filename(url), unit_tokens))
    )
    if type_matches:
        return type_matches

    fallback = [
        url
        for url in gallery
        if "mat-bang" not in _normalize_filename(url) and "matbang" not in _normalize_filename(url)
    ]

    if normalized_unit_type == _ZONE_OVERVIEW_UNIT_TYPE:
        without_unit_photos = [url for url in fallback if not _UNIT_TYPE_PHOTO_PATTERN.search(_normalize_filename(url))]
        if without_unit_photos:
            fallback = without_unit_photos

    sub_zone_tokens = _sub_zone_tokens(project_name)
    if sub_zone_tokens:
        sub_zone_matches = [
            url for url in gallery if any(token in _normalize_filename(url) for token in sub_zone_tokens)
        ]
        if sub_zone_matches:
            return list(dict.fromkeys([*sub_zone_matches, *fallback]))

    return fallback


_REAL_PHOTO_FOLDER = "hinh-anh-thuc-te/"
_AMENITY_FOLDER = "tien-ich/"

_FLOOR_PLAN_SPEC_PATTERN = re.compile(r"mat-bang-tang-([0-9a-z\-]*?)-toa-")
_FLOOR_PLAN_SHEET_PATTERN = re.compile(r"mat-bang-(?:tang|toa|khu)-")


def _inventory_listing_images(gallery: list[str], unit_type: str, tower: str, unit_code: str) -> list[str]:
    """The four photos that describe one confirmed unit, in reading order: layout, its
    floor's plan, one real subdivision photo, one amenity photo. Without a layout the real
    photo leads, so the card opens on something concrete rather than a technical drawing.

    Each component is simply absent when the catalogue has no such photo — padding the gap
    would put a picture of the wrong thing under a specific mã căn.
    """
    layouts = _unit_layout_photos(gallery, unit_type, tower)
    floor_plan = _floor_plan_photo(gallery, tower, unit_code)
    real_photo = _first_in_folder(gallery, _REAL_PHOTO_FOLDER)
    amenity = _first_in_folder(gallery, _AMENITY_FOLDER)

    ordered = [*layouts, floor_plan, real_photo, amenity] if layouts else [real_photo, floor_plan, amenity]
    return list(dict.fromkeys(url for url in ordered if url))


def _unit_layout_photos(gallery: list[str], unit_type: str, tower: str) -> list[str]:
    """Layout drawings of this unit type (`can-ho-2-ngu-zr1...`), the unit's own tower
    preferred when the filename names one.

    Floor/tower/zone sheets are excluded even when they carry a matching bedroom count:
    those draw a whole floor, not this apartment, and `_floor_plan_photo` places the right
    one of those separately.
    """
    tokens = _unit_type_tokens(_normalize(unit_type))
    if not tokens:
        return []

    matches = [
        url
        for url in gallery
        if _matches_any_filename_token(_normalize_filename(url), tokens)
        and not _FLOOR_PLAN_SHEET_PATTERN.search(_normalize_filename(url))
    ]
    if not matches:
        return []

    same_tower = [url for url in matches if _names_tower(_normalize_filename(url), tower)]
    return list(dict.fromkeys(same_tower or matches))


def _floor_plan_photo(gallery: list[str], tower: str, unit_code: str) -> str | None:
    """The floor plan for this unit's own floor, falling back to its tower's whole-tower
    sheet, or None when the tower has neither.

    The floor is the first two digits of the unit code's last segment (`OCP1-ZR1-0101` ->
    floor 1), which is how the inventory numbers a unit; the sheets name the floors they
    cover in the filename. A sheet for the wrong floor is never returned — the tower-wide
    sheet is the honest fallback, since it genuinely does describe every floor.
    """
    sheets = _tower_photos(gallery, tower)
    if not sheets:
        return None

    floor = _floor_from_unit_code(unit_code)
    if floor is not None:
        for url in sheets:
            covered = _floor_plan_floors(_normalize_filename(url))
            if covered and floor in covered:
                return url

    for url in sheets:
        if _floor_plan_floors(_normalize_filename(url)) is None:
            return url
    return None


def _floor_from_unit_code(unit_code: str) -> int | None:
    """Floor number encoded in a mã căn: the first two digits of its last segment."""
    digits = "".join(char for char in unit_code.strip().rsplit("-", 1)[-1] if char.isdigit())
    return int(digits[:2]) if len(digits) >= 2 else None


def _floor_plan_floors(filename: str) -> set[int] | None:
    """Floors one sheet covers, or None when its filename names no floor at all.

    Two numbers are an inclusive range (`tang-3-24`); three or more are exactly those
    floors (`tang-22-24-26-28`, whose odd neighbours have their own sheet). `-va-` joins
    two groups. None means a whole-tower sheet, which `_floor_plan_photo` uses as its
    fallback — distinct from a set that merely lacks this floor.
    """
    match = _FLOOR_PLAN_SPEC_PATTERN.search(filename)
    if not match:
        return None

    floors: set[int] = set()
    for group in match.group(1).split("-va-"):
        numbers = [int(part) for part in group.split("-") if part.isdigit()]
        if not numbers:
            continue
        if len(numbers) == 1:
            floors.add(numbers[0])
        elif len(numbers) == 2:
            floors.update(range(min(numbers), max(numbers) + 1))
        else:
            floors.update(numbers)
    return floors or None


def _first_in_folder(gallery: list[str], folder: str) -> str | None:
    """The first photo filed under one catalogue folder, or None when it holds none."""
    return next((url for url in gallery if _normalize_filename(url).startswith(folder)), None)


def _names_tower(filename: str, tower: str) -> bool:
    """Whether a filename names this exact tower, in either spelling."""
    if not tower.strip():
        return False
    slug = _normalize(tower).replace(" ", "-")
    return any(
        re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", filename) for token in {slug, slug.replace(".", "-")}
    )


def _tower_photos(gallery: list[str], tower: str) -> list[str]:
    """Photos filed under one exact tower code, or [] when the gallery has none.

    The API and the filenames spell a tower differently (`S1.06` vs `toa-s1-07`), so both
    the dot and hyphen forms are tried. Empty on no match is the point: callers fall
    through rather than showing a photo of the wrong tower.
    """
    if not tower.strip():
        return []

    slug = _normalize(tower).replace(" ", "-")
    tokens = {f"toa-{slug}", f"toa-{slug.replace('.', '-')}"}
    return [
        url
        for url in gallery
        if any(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", _normalize_filename(url)) for token in tokens)
    ]


def select_listing_amenities(project: Project, max_amenities: int = 4) -> list[str]:
    """A few named amenities for a listing card, read straight from the catalogue record —
    never left for the model to invent, like the image URLs."""
    amenities = (project.details or {}).get("amenities") or []
    names = [item["name"] for item in amenities if isinstance(item, dict) and isinstance(item.get("name"), str)]
    return names[:max_amenities]


def _filter_by_topic(gallery: list[str], normalized_query: str, known_towers: list[str] | None = None) -> list[str]:
    """Narrow the gallery to the topic the question named.

    Falls back to the whole gallery when the question named no topic, or one the catalogue
    has no picture of: returning nothing to someone who asked to see something is worse.
    """
    exact_tower_tokens = _tower_tokens(normalized_query, known_towers)
    if exact_tower_tokens:
        return [url for url in gallery if any(token in _normalize_filename(url) for token in exact_tower_tokens)]

    view_match = _filter_view_images(gallery, normalized_query)
    if view_match is not None:
        return view_match

    tokens = _wanted_tokens(normalized_query)
    if not tokens:
        return gallery

    matched = [url for url in gallery if any(token in _normalize_filename(url) for token in tokens)]
    return matched or gallery


def _auto_attach_images(gallery: list[str], normalized_query: str, known_towers: list[str] | None = None) -> list[str]:
    """The automatic route's selection: matching photos only, capped.

    Unlike `_filter_by_topic` it never widens to the whole gallery — nobody asked for these,
    so an unmatched topic yields no photo. A question naming no visual topic gets the
    establishing shots, which illustrate without claiming to depict anything specific.
    """
    exact_tower_tokens = _tower_tokens(normalized_query, known_towers)
    if exact_tower_tokens:
        exact = [url for url in gallery if any(token in _normalize_filename(url) for token in exact_tower_tokens)]
        return exact[:_AUTO_ATTACH_MAX_IMAGES]

    view_match = _filter_view_images(gallery, normalized_query)
    if view_match is not None:
        return view_match[:_AUTO_ATTACH_MAX_IMAGES]

    tokens = _wanted_tokens(normalized_query) if _subject_tokens(normalized_query) else list(_OVERVIEW_TOKENS)

    matched = [url for url in gallery if any(token in _normalize_filename(url) for token in tokens)]
    return matched[:_AUTO_ATTACH_MAX_IMAGES]


def _filter_view_images(gallery: list[str], normalized_query: str) -> list[str] | None:
    """Require filename evidence before claiming a photo depicts a unit's view.

    None means this is not a view question. A qualified view ("view hồ") needs both the
    view label and that subject in the filename — image order and project identity cannot
    prove which direction a photograph faces.
    """
    view_filename_tokens = ("view-", "tam-nhin", "huong-nhin")
    if not _contains_phrase(normalized_query, ("view", "tam nhin", "huong nhin", "huong can")):
        return None

    explicit_view_images = [
        url for url in gallery if any(token in _normalize_filename(url) for token in view_filename_tokens)
    ]
    subject_tokens = [token for token in _subject_tokens(normalized_query) if token not in view_filename_tokens]
    if not subject_tokens:
        return explicit_view_images
    return [url for url in explicit_view_images if any(token in _normalize_filename(url) for token in subject_tokens)]


def _subject_tokens(normalized_query: str) -> list[str]:
    """Filename tokens for the subjects named — the things the catalogue photographs."""
    tokens: list[str] = []
    for phrases, filename_tokens in _TOPIC_TOKENS:
        if _contains_phrase(normalized_query, phrases):
            tokens.extend(filename_tokens)
    return tokens


def _unit_type_tokens(normalized_query: str) -> list[str]:
    """Filename tokens for a bedroom count or "studio" named in the text — nothing else.

    Kept separate from `_subject_tokens`, which carries the generic "mat-bang" token: with
    that included, any whole-tower floor plan would match every unit type in the tower.
    """
    tokens: list[str] = []

    plus_one = re.search(r"\b(\d)\s*(?:pn|phong\s*ngu|ngu)\s*\+\s*1\b", normalized_query)
    if plus_one:
        bedrooms = plus_one.group(1)
        tokens.extend(
            [
                f"{bedrooms}pn1",
                f"{bedrooms}pn-1",
                f"{bedrooms}-pn-1",
                f"{bedrooms}-phong-ngu-1",
                f"{bedrooms}-ngu-1",
            ]
        )
    else:
        for bedrooms in re.findall(r"\b(\d)\s*(?:pn|phong\s*ngu|ngu)\b", normalized_query):
            tokens.extend([f"{bedrooms}pn", f"{bedrooms}-phong-ngu", f"{bedrooms}-pn", f"{bedrooms}-ngu"])

    if re.search(r"\bstudio\b", normalized_query):
        tokens.append("studio")

    for unit_type in ("duplex", "penthouse"):
        if re.search(rf"\b{unit_type}\b", normalized_query):
            tokens.append(unit_type)

    for phrase, token in (("don lap", "don-lap"), ("song lap", "song-lap"), ("lien ke", "lien-ke")):
        if phrase in normalized_query:
            tokens.append(token)

    return tokens


def _matches_any_filename_token(filename: str, tokens: list[str]) -> bool:
    """Match complete slug tokens, so a 2PN listing never selects a 2PN+1 layout."""
    return any(re.search(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", filename) for token in tokens)


def _wanted_tokens(normalized_query: str) -> list[str]:
    """Subjects plus qualifiers — everything usable to narrow the gallery."""
    tokens = _subject_tokens(normalized_query)
    tokens.extend(_unit_type_tokens(normalized_query))

    return tokens


def _tower_tokens(normalized_query: str, known_towers: list[str] | None = None) -> list[str]:
    """Exact named tower qualifiers in both dot and hyphen filename conventions."""
    matched_names = [
        tower
        for tower in known_towers or []
        if isinstance(tower, str) and re.search(rf"(?<!\w){re.escape(_normalize(tower))}(?!\w)", normalized_query)
    ]
    if not matched_names:
        matched_names = re.findall(r"\b(?:toa|tower)\s*([a-z]{1,5}\d+(?:\.\d+)?)\b", normalized_query)

    tokens: list[str] = []
    for name in matched_names:
        slug = _normalize(name).replace(" ", "-")
        tokens.extend((f"toa-{slug}", f"toa-{slug.replace('.', '-')}"))
    return list(dict.fromkeys(tokens))


def _best_match(db: Session, haystack: str) -> Project | None:
    """The project whose name or slug appears in the text, longest match winning.

    Catalogue names nest — "Vinhomes Ocean Park" matches whenever "Vinhomes Ocean Park 3"
    does — and the more specific one is what was asked about.
    """
    best: Project | None = None
    best_length = 0
    projects = db.query(Project).all()

    for project in projects:
        for normalized in _project_aliases(project):
            if len(normalized) < _MIN_NAME_LENGTH or normalized not in haystack:
                continue
            if len(normalized) > best_length:
                best, best_length = project, len(normalized)

    if best is not None:
        return best

    compact_haystack = haystack.replace(" ", "")
    for project in projects:
        for normalized in _project_aliases(project):
            compact_alias = normalized.replace(" ", "")
            if len(compact_alias) < _MIN_NAME_LENGTH or compact_alias not in compact_haystack:
                continue
            if len(compact_alias) > best_length:
                best, best_length = project, len(compact_alias)

    return best


def _project_aliases(project: Project) -> set[str]:
    """All catalogue labels a customer can reasonably use for one project/sub-zone."""
    details = project.details or {}
    info = details.get("project") or {}
    raw = {
        project.id.replace("-", " "),
        project.name,
        project.name.split(" - ", 1)[0] if project.name else None,
        info.get("name"),
        info.get("full_name"),
        info.get("alternate_name"),
        info.get("sub_zone"),
    }
    aliases = {_normalize(str(value)) for value in raw if value}
    configured_aliases = info.get("aliases") or []
    if isinstance(configured_aliases, list):
        aliases.update(_normalize(str(value)) for value in configured_aliases if value)
    aliases.update(alias.removeprefix("the ") for alias in tuple(aliases))
    aliases.update(alias.removeprefix("vinhomes ") for alias in tuple(aliases))
    return {alias for alias in aliases if alias}


def _known_project_towers(details: dict) -> set[str]:
    overview = ((details.get("project") or {}).get("overview") or {}).get("towers") or []
    tower_details = details.get("tower_details") or {}
    raw = [*(overview if isinstance(overview, list) else []), *tower_details.keys()]
    return {_normalize(str(value)) for value in raw if value}


def _contains_phrase(haystack: str, phrases: tuple[str, ...]) -> bool:
    """Whole-word phrase match.

    Substring matching fails quietly here: "anh" sits inside "thanh toán" and "ho" inside
    "cho", firing the image tool on payment-schedule questions.
    """
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", haystack) for phrase in phrases)


def _normalize(text: str) -> str:
    """Lowercase, strip diacritics and collapse separators, so "Hải Âu", "hai au" and the
    slug "hai-au" all reduce to one comparable string."""
    return " ".join(strip_diacritics(text).lower().replace("-", " ").split())


def _normalize_filename(url: str) -> str:
    """The filename in slug form, prefixed with its catalogue folder when it sits in one.

    The folder is often the only record of what a photo shows — Zenpark's amenity shots are
    named `be-boi-4-mua-...`, `vuon-nhat-...`, never "tien ich". Only `_CATEGORY_FOLDERS`
    count: the preceding segment is usually the project slug, and four catalogues are named
    `shop-thuong-mai-*`, which would match "shop" for every photo in them.
    """
    parts = url.rsplit("/", 2)
    name = strip_diacritics(parts[-1]).lower()
    if len(parts) < 3:
        return name
    folder = strip_diacritics(parts[-2]).lower().replace("_", "-")
    if folder not in _CATEGORY_FOLDERS:
        return name
    return f"{folder}/{name}"
