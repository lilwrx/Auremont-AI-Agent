"""RiskCheck — decide whether an answer needs the HITL card before a Sale sends it out.

The flag this module returns is exactly what unlocks `POST /hitl/{message_id}/confirm`
(`routers/hitl.py` rejects with 400 when `requires_hitl=False`). In other words: missing a
price-related answer here means a Sale copies figures straight to a customer with nobody
re-reading them.

The rules therefore deliberately **prefer a false positive to a miss**: an unnecessary
confirmation card costs the Sale one click, whereas a wrong price commitment can turn into
a contract dispute.

Regex rather than an LLM call: this decision sits on the path of every single answer, has
to fit the sub-3-second budget, and must not depend on an LLM being available. To upgrade
it to a classifier later, swap the function body and keep the signature.
"""

import re

from backend.utils.text import strip_diacritics

_MONEY_WITH_UNIT = re.compile(
    r"\d[\d.,]*\s*(ty|ti|trieu|nghin|ngan|vnd|dong|d)\b",
    re.IGNORECASE,
)

_BARE_LARGE_NUMBER = re.compile(r"\b\d{9,}\b")

_PERCENTAGE = re.compile(r"\d[\d.,]*\s*%")

_COMMITMENT_KEYWORDS = (
    "cam kết",
    "đảm bảo",
    "bảo đảm",
    "chắc chắn",
    "hợp đồng",
    "ký kết",
    "đặt cọc",
    "giữ chỗ",
    "booking",
    "chiết khấu",
    "ưu đãi",
    "khuyến mãi",
    "lãi suất",
    "thanh toán",
    "trả góp",
    "vay",
    "hỗ trợ tài chính",
    "sổ hồng",
    "sổ đỏ",
    "bàn giao",
    "pháp lý",
)


def detect_commitment_risk(answer: str) -> bool:
    """`True` when the answer touches price or commitments -> the HITL card is mandatory.

    Matches against the diacritic-stripped text so answers written without accents (or
    mixing both) are still caught. A miss here means the Sale sends figures straight to a
    customer without the mandatory confirmation step.
    """
    if not answer or not answer.strip():
        return False

    normalized = strip_diacritics(answer)

    if _MONEY_WITH_UNIT.search(normalized) or _BARE_LARGE_NUMBER.search(normalized) or _PERCENTAGE.search(normalized):
        return True

    return any(strip_diacritics(keyword) in normalized for keyword in _COMMITMENT_KEYWORDS)
