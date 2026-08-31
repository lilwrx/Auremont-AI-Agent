"""Resolve exact, structured project facts that are too granular for document RAG.

Project PDFs often describe a whole cluster (for example "30-32 tầng") while a
question names one tower ("P4").  The project catalogue can carry the exact tower
record, so this module exposes only that matching record to Generate and Verify.  It
never sends the complete catalogue to the model and never guesses when a tower code is
ambiguous across projects.
"""

import re
from dataclasses import dataclass

from sqlalchemy.orm import Session

from backend.models.project import Project
from backend.utils.text import strip_diacritics

_PROFILE_TERMS = (
    "thong tin toa",
    "thuoc phan khu",
    "bao nhieu tang",
    "quy mo",
    "tiep giap",
    "vi tri",
    "ranh gioi",
)
_NON_PROFILE_TERMS = (
    "gia",
    "chinh sach",
    "thanh toan",
    "phap ly",
    "ban giao",
    "tien ich",
    "dien tich can",
    "loai can",
    "ton kho",
    "con trong",
    "huong can",
    "view can",
)

_PROJECT_PROFILE_TERMS = (
    "du an",
    "vi tri",
    "o dau",
    "di chuyen",
    "ket noi",
    "giao thong",
    "bao xa",
    "mat bao lau",
    "quy hoach",
    "ha tang",
    "duong nao",
    "chu dau tu",
    "don vi phat trien",
    "quy mo",
    "bao nhieu toa",
    "toa nao",
    "mo ban",
    "bao nhieu can",
    "loai can",
    "loai san pham",
    "dien tich",
    "ban giao",
    "tien do",
    "so huu",
    "phap ly",
    "so hong",
    "gia",
    "ngan sach",
    "chinh sach",
    "chiet khau",
    "uu dai",
    "khuyen mai",
    "thanh toan",
    "dat coc",
    "vay",
    "lai suat",
    "an han",
    "ngan hang",
    "vat",
    "bao tri",
    "tien ich",
    "be boi",
    "gym",
    "cong vien",
    "truong hoc",
    "benh vien",
    "trung tam thuong mai",
)
_PRICE_TERMS = ("gia", "bao nhieu tien", "ngan sach", "tam gia")
_POLICY_TERMS = (
    "chinh sach",
    "chiet khau",
    "uu dai",
    "khuyen mai",
    "thanh toan",
    "dat coc",
    "vay",
    "lai suat",
    "an han",
    "ngan hang",
    "vat",
    "bao tri",
)
_AMENITY_TERMS = (
    "tien ich",
    "be boi",
    "gym",
    "cong vien",
    "truong hoc",
    "benh vien",
    "trung tam thuong mai",
)


@dataclass(frozen=True)
class TowerContextResult:
    """Structured context plus whether it fully covers this exact question."""

    text: str = ""
    complete: bool = False


def tower_context(db: Session | None, project_id: str | None, query: str) -> str:
    """Compatibility wrapper returning only the prompt-ready text."""
    return resolve_tower_context(db, project_id, query).text


def project_profile_context(db: Session | None, project_id: str | None, query: str) -> str:
    """Return relevant public facts already stored in ``Project.details``.

    Project seed data is structured catalogue data, not a current inventory feed. This
    context makes location, overview, reference pricing, published policies and amenities
    available to both Generate and Verify without pretending that a catalogue range is a
    currently available unit or that an undated promotion is still active.
    """
    if db is None or not callable(getattr(db, "get", None)) or not project_id or not query.strip():
        return ""
    normalized = _normalize(query)
    if not _has_any(normalized, _PROJECT_PROFILE_TERMS):
        return ""

    project = db.get(Project, project_id)
    if project is None:
        return ""
    details = project.details or {}
    info = details.get("project") or {}
    overview = info.get("overview") or {}
    lines = ["DỮ LIỆU HỒ SƠ DỰ ÁN CÓ CẤU TRÚC (catalogue dự án):"]

    _append(lines, "Tên dự án", info.get("full_name") or info.get("name") or project.name)
    _append(lines, "Chủ đầu tư", info.get("developer"))
    _append(lines, "Đại phân khu", info.get("sub_zone"))
    _append(lines, "Vị trí", _format_location(info.get("location")))
    _append(lines, "Mô tả", info.get("description"))
    _append(lines, "Mô tả kết nối", info.get("location_description"))
    _append(lines, "Điểm vị trí", info.get("location_highlights"))

    overview_labels = {
        "towers": "Các tòa",
        "towers_on_sale": "Các tòa mở bán trong catalogue",
        "total_units": "Tổng số căn",
        "unit_types": "Loại căn",
        "area_range": "Khoảng diện tích",
        "floors": "Quy mô tầng toàn phân khu",
        "handover": "Mốc bàn giao trong catalogue",
        "ownership": "Hình thức sở hữu trong catalogue",
    }
    for key, label in overview_labels.items():
        _append(lines, label, overview.get(key))

    if _has_any(normalized, _PRICE_TERMS):
        pricing = details.get("pricing") or []
        if pricing:
            lines.append("GIÁ CATALOGUE THAM KHẢO (không xác nhận căn đang còn):")
        for row in pricing:
            if not isinstance(row, dict):
                continue
            unit_type = row.get("apartment_type") or row.get("type") or row.get("category") or "Chưa phân loại"
            area = _range_text(row.get("size_min_sqm"), row.get("size_max_sqm"), "m²")
            price = _price_text(row.get("price_min"), row.get("price_max"), row.get("price_note"))
            lines.append(f"- {unit_type}: diện tích {area}; giá tham khảo {price}")
        if pricing:
            lines.append("Trạng thái và giá chốt của từng mã căn phải xác nhận từ tồn kho real-time.")

    if _has_any(normalized, _POLICY_TERMS):
        policies = details.get("sales_policies") or []
        if policies:
            lines.append("CHÍNH SÁCH LƯU TRONG CATALOGUE:")
        for policy in policies:
            if isinstance(policy, dict) and policy.get("content"):
                policy_type = str(policy.get("type") or "Chính sách").strip()
                lines.append(f"- {policy_type}: {str(policy['content']).strip()}")
        if policies:
            lines.append(
                "Nếu catalogue không ghi ngày hiệu lực/hết hạn, phải nói rõ cần xác nhận bản chính sách hiện hành; "
                "không được tự khẳng định ưu đãi vẫn còn."
            )

    if _has_any(normalized, _AMENITY_TERMS):
        amenities = details.get("amenities") or []
        if amenities:
            lines.append("TIỆN ÍCH TRONG CATALOGUE:")
        for amenity in amenities:
            if not isinstance(amenity, dict) or not amenity.get("name"):
                continue
            category = f" ({amenity['category']})" if amenity.get("category") else ""
            lines.append(f"- {str(amenity['name']).strip()}{category}")

    lines.append(
        "Chỉ dùng các trường được liệt kê. Không suy ra thời gian di chuyển, tình trạng giao thông, "
        "pháp lý chi tiết, phí, thông số cấp mã căn hoặc dự báo đầu tư khi hồ sơ không ghi."
    )
    return "\n".join(lines)


def resolve_tower_context(db: Session | None, project_id: str | None, query: str) -> TowerContextResult:
    """Resolve every catalogue tower, with exact facts where the catalogue has them.

    `overview.towers` provides complete identifier coverage across subdivisions. It is
    used only to identify the tower and its subdivision — aggregate overview values such
    as `floors: 30-32` are deliberately never promoted to a tower fact. `tower_details`
    supplies exact per-tower fields when available.
    """
    if db is None or not query.strip():
        return TowerContextResult()

    projects = _candidate_projects(db, project_id)
    matches: list[tuple[Project, str, dict]] = []
    normalized_query = _normalize(query)

    for project in projects:
        details = project.details or {}
        tower_details = details.get("tower_details") or {}
        known_towers = _known_towers(details)
        for tower_name in known_towers:
            if _mentions_tower(normalized_query, tower_name):
                facts = tower_details.get(tower_name) or {}
                matches.append((project, tower_name, facts))

    if len(matches) != 1:
        return TowerContextResult()

    project, tower_name, facts = matches[0]
    details = project.details or {}
    project_info = details.get("project") or {}
    subdivision = facts.get("subdivision") or project_info.get("name") or project.name
    parent_sub_zone = facts.get("parent_sub_zone") or project_info.get("sub_zone")
    lines = [
        f"Tòa: {tower_name}",
        f"Phân khu: {subdivision}",
    ]
    _append(lines, "Đại phân khu", parent_sub_zone)

    asks_subdivision = _has_any(normalized_query, ("phan khu", "khu nao"))
    asks_scale = _has_any(normalized_query, ("tang", "cao", "quy mo"))
    asks_floor_use = _has_any(normalized_query, ("cong nang", "tang nao", "shophouse", "lanh nan"))
    asks_road = _has_any(normalized_query, ("duong", "vi tri", "tiep giap"))
    asks_boundaries = _has_any(normalized_query, ("ranh gioi", "bon phia", "xung quanh", "giap toa"))
    has_specific_fields = asks_subdivision or asks_scale or asks_floor_use or asks_road or asks_boundaries

    if asks_scale or not has_specific_fields:
        _append(lines, "Quy mô", facts.get("scale"))
    if asks_floor_use or not has_specific_fields:
        _append(lines, "Công năng tầng", facts.get("floor_use"))
    if asks_road or not has_specific_fields:
        _append(lines, "Tiếp giáp giao thông", facts.get("road_adjacency"))
    if asks_boundaries or not has_specific_fields:
        _append(lines, "Ranh giới vị trí", facts.get("boundaries"))

    required_values = []
    if asks_subdivision:
        required_values.append(subdivision)
    if asks_scale:
        required_values.append(facts.get("scale"))
    if asks_floor_use:
        required_values.append(facts.get("floor_use"))
    if asks_road:
        required_values.append(facts.get("road_adjacency"))
    if asks_boundaries:
        required_values.append(facts.get("boundaries"))
    complete = all(bool(value) for value in required_values) if has_specific_fields else bool(facts)

    if not complete:
        lines.append(
            "Phạm vi dữ liệu: catalogue xác nhận danh tính tòa và phân khu; các thuộc tính "
            "cấp tòa còn thiếu phải tra từ tài liệu. Không được dùng khoảng tổng quan của "
            "toàn phân khu như một giá trị chính xác của tòa."
        )

    text = (
        "DỮ LIỆU HỒ SƠ TÒA CÓ CẤU TRÚC (catalogue dự án):\n"
        + "\n".join(lines)
        + "\nCác trường có giá trị ở trên là nguồn sự thật cho đúng tòa được hỏi. Khi tài "
        "liệu tổng quan khác một trường đã có trong hồ sơ tòa, bắt buộc dùng hồ sơ tòa. "
        "Chỉ trả lời các ý người dùng hỏi; không bổ sung một thuộc tính riêng của tòa nếu "
        "không có bằng chứng ở hồ sơ hoặc tài liệu. Không biến thông tin tiếp giáp của "
        "toàn phân khu thành tiếp giáp trực tiếp của tòa."
    )
    return TowerContextResult(text=text, complete=complete)


def is_tower_profile_query(query: str) -> bool:
    """Whether structured tower facts fully own the requested topic.

    Mixed questions (for example "P4 có giá và chính sách gì?") still need document RAG.
    A pure identity/height/location question should not receive a generic PDF chunk that
    can re-introduce cluster-level values or unasked-for tower attributes.
    """
    normalized = _normalize(query)
    return _has_any(normalized, _PROFILE_TERMS) and not _has_any(normalized, _NON_PROFILE_TERMS)


def _candidate_projects(db: Session, project_id: str | None) -> list[Project]:
    if project_id:
        project = db.get(Project, project_id)
        return [project] if project is not None else []
    return db.query(Project).all()


def _known_towers(details: dict) -> list[str]:
    tower_details = details.get("tower_details") or {}
    overview = (details.get("project") or {}).get("overview") or {}
    overview_towers = overview.get("towers") or []
    if not isinstance(overview_towers, list):
        overview_towers = []

    return list(
        dict.fromkeys(
            tower for tower in [*overview_towers, *tower_details.keys()] if isinstance(tower, str) and tower.strip()
        )
    )


def _mentions_tower(normalized_query: str, tower_name: str) -> bool:
    normalized_tower = _normalize(tower_name)
    return bool(re.search(rf"(?<!\w){re.escape(normalized_tower)}(?!\w)", normalized_query))


def _normalize(text: str) -> str:
    return " ".join(strip_diacritics(text).lower().replace("-", " ").split())


def _has_any(haystack: str, phrases: tuple[str, ...]) -> bool:
    return any(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", haystack) for phrase in phrases)


def _append(lines: list[str], label: str, value: object) -> None:
    if isinstance(value, str) and value.strip():
        lines.append(f"{label}: {value.strip()}")
    elif isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if items:
            lines.append(f"{label}: {'; '.join(items)}")


def _format_location(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if not isinstance(value, dict):
        return None
    ordered = [value.get("within"), value.get("district"), value.get("city")]
    parts = [str(part).strip() for part in ordered if part is not None and str(part).strip()]
    return ", ".join(dict.fromkeys(parts)) or None


def _number(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value) if isinstance(value, int | float) else float(str(value))
    except (TypeError, ValueError):
        return None


def _range_text(minimum: object, maximum: object, suffix: str) -> str:
    lower = _number(minimum)
    upper = _number(maximum)
    if lower is None and upper is None:
        return "chưa có dữ liệu"
    if lower is None:
        return f"đến {upper:g} {suffix}"
    if upper is None or lower == upper:
        return f"{lower:g} {suffix}"
    return f"{lower:g}–{upper:g} {suffix}"


def _price_text(minimum: object, maximum: object, note: object) -> str:
    lower = _number(minimum)
    upper = _number(maximum)
    if lower is None and upper is None:
        return str(note).strip() if note is not None and str(note).strip() else "chưa có dữ liệu"
    return _range_text(
        lower / 1_000_000_000 if lower is not None else None,
        upper / 1_000_000_000 if upper is not None else None,
        "tỷ đồng",
    )
