import re

from backend.services import answer_images_service
from backend.utils.text import strip_diacritics


def wants_images_for_prompt(query: str) -> bool:
    return answer_images_service.wants_images(query)


_IMAGE_DENIAL_MARKERS = (
    "khong chua hinh anh",
    "khong co hinh anh",
    "khong co anh",
    "khong co tep anh",
    "khong co file anh",
    "chua co hinh anh",
    "chua co anh",
    "khong hien thi duoc anh",
    "khong co hinh anh truc quan",
    "hinh anh truc quan de hien thi",
    "xin anh",
)


def drop_image_denials(answer: str, images: list[dict]) -> str:
    if not images:
        return answer

    kept = [
        line
        for line in answer.splitlines()
        if not any(marker in strip_diacritics(line).lower() for marker in _IMAGE_DENIAL_MARKERS)
    ]
    cleaned = "\n".join(kept).strip()
    if cleaned:
        return cleaned

    return f"- Đang hiển thị {len(images)} ảnh {images[0].get('project_name') or 'dự án'} bên dưới."


_FALSE_IMAGE_CONFIRMATION_MARKERS = (
    "dang hien thi",
    "da hien thi",
    "hien thi ngay tren man hinh",
    "ngay tren man hinh",
    "duoi tin nhan nay",
    "da dinh kem",
    "da gui hinh anh",
    "da gui cac hinh anh",
    "gui hinh anh thuc te",
)


def drop_false_image_confirmations(answer: str, images: list[dict]) -> str:
    if images:
        return answer

    kept = [
        line
        for line in answer.splitlines()
        if not any(marker in strip_diacritics(line).lower() for marker in _FALSE_IMAGE_CONFIRMATION_MARKERS)
    ]
    cleaned = "\n".join(kept).strip()
    if cleaned:
        return cleaned

    return "Hiện tại chưa có ảnh phù hợp với yêu cầu này ạ."


_SPELLED_NUMBERS = {
    "mot": 1,
    "hai": 2,
    "ba": 3,
    "bon": 4,
    "tu": 4,
    "nam": 5,
    "sau": 6,
    "bay": 7,
    "tam": 8,
    "chin": 9,
    "muoi": 10,
}

_TOTAL_CUE = (
    r"(?:tổng\s+cộng|tổng\s+số|tất\s+cả|(?:hiện\s+)?(?:đang\s+)?có\s+tổng"
    r"|tìm\s+được|tìm\s+thấy|hiện\s+có|hiện\s+còn|hiện\s+đang\s+có)"
)
_UNIT_COUNT_PATTERN = re.compile(
    rf"(?P<cue>\b{_TOTAL_CUE}\s+)(?<![\d,.])(?P<count>\d{{1,3}}|[^\W\d_]+)(?P<tail>\s+căn\b)",
    re.IGNORECASE,
)


def correct_unit_count(answer: str, unit_count: int) -> str:
    if unit_count <= 0 or not answer:
        return answer

    def replace(match: re.Match[str]) -> str:
        raw = match.group("count")
        if raw.isdigit():
            stated = int(raw)
        else:
            stated = _SPELLED_NUMBERS.get(strip_diacritics(raw).lower(), -1)
            if stated < 0:
                return match.group(0)
        if stated == unit_count:
            return match.group(0)
        return f"{match.group('cue')}{unit_count}{match.group('tail')}"

    return _UNIT_COUNT_PATTERN.sub(replace, answer, count=1)
