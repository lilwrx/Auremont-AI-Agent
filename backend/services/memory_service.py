"""Long-term memory — what we remember about a person across conversations, above the
short-term `history` turns threaded into each prompt.

Namespaces never mix: `memory:customer:{id}` is one person's own preferences;
`memory:sale-session:{id}` is the end customer behind one Sale consultation, never shared
across sessions; `memory:sale:{id}` is a legacy namespace no longer read or written.

Three rules, each guarding a specific wrong answer:

1. **Fail open.** Every entry point degrades to "no profile" on exception — a Redis outage
   costs convenience, never the ability to answer.
2. **Remember questions, never answers.** Facts come from what the human typed; storing
   the model's own words would harden a hallucination into a remembered preference.
3. **Preferences are hints about a person, not facts about a project.** Never grounding —
   the model still reads every number from retrieved documents.
"""

import json
import logging
import re
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from backend.core.config import get_settings
from backend.core.redis_client import get_redis_client
from backend.utils.text import strip_diacritics
from backend.utils.vnd import BUDGET_UNIT_ALTERNATION

logger = logging.getLogger(__name__)

MAX_ITEMS_PER_FIELD = 5

UNIT_TYPE_PATTERN = re.compile(r"\b(\d\s?PN|studio|shophouse|penthouse|duplex)\b", re.IGNORECASE)

# Shared vocabulary keeps supported budget-unit spellings consistent.
BUDGET_PATTERN = re.compile(rf"(\d+(?:[.,]\d+)?)\s*({BUDGET_UNIT_ALTERNATION})\b", re.IGNORECASE)
BUDGET_RANGE_PATTERN = re.compile(
    rf"(\d+(?:[.,]\d+)?)\s*(?:-|–|đến|den|tới|toi)\s*(\d+(?:[.,]\d+)?)\s*({BUDGET_UNIT_ALTERNATION})\b",
    re.IGNORECASE,
)

BUDGET_CONTEXT_PATTERN = re.compile(
    r"(ngân\s*sách|ngan\s*sach|tài\s*chính|tai\s*chinh|budget"
    r"|tầm\s*giá|tam\s*gia|khoảng\s*giá|khoang\s*gia|trong\s*tầm|trong\s*tam"
    r"|có\s*sẵn|co\s*san|dư\s*(?:khoảng|chừng)?|du\s*(?:khoang|chung)?"
    r"|chỉ\s*có|chi\s*co|tối\s*đa|toi\s*da|dưới|duoi|trên\s*dưới|tren\s*duoi"
    r"|muốn\s*mua|muon\s*mua|định\s*mua|dinh\s*mua|tìm\s*căn|tim\s*can)",
    re.IGNORECASE,
)

PRICE_QUESTION_PATTERN = re.compile(
    r"(giá\s*(?:căn|bán|gốc|niêm)|gia\s*(?:can|ban|goc|niem)"
    r"|bao\s*nhiêu|bao\s*nhieu|có\s*đắt|co\s*dat|đắt\s*hơn|dat\s*hon|rẻ\s*hơn|re\s*hon)",
    re.IGNORECASE,
)


@dataclass
class UserProfile:
    """What we remember about one person. Every field is optional and may be empty."""

    unit_types: list[str] = field(default_factory=list)
    budgets: list[str] = field(default_factory=list)
    projects: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)

    def is_empty(self) -> bool:
        return not (self.unit_types or self.budgets or self.projects or self.topics)


def customer_key(customer_id: int) -> str:
    return f"memory:customer:{customer_id}"


def sale_key(sale_id: int) -> str:
    """Legacy Sale-level key; do not use for customer consultation sessions."""
    return f"memory:sale:{sale_id}"


def sale_session_key(session_id: int) -> str:
    """Long-term profile for the single customer represented by a Sale session."""
    return f"memory:sale-session:{session_id}"


def load_profile(key: str) -> UserProfile:
    """Read a profile. Any failure — Redis down, corrupt JSON — yields an empty profile."""
    client = get_redis_client()
    if client is None:
        return UserProfile()

    try:
        raw = client.get(key)
    except Exception:
        logger.warning(
            "Doc ho so ghi nho that bai; coi nhu chua co ho so.",
            exc_info=True,
            extra={"event": "memory.load.failed", "key": key},
        )
        return UserProfile()

    if not raw:
        return UserProfile()

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Ho so ghi nho hong; bo qua.", extra={"event": "memory.load.corrupt", "key": key})
        return UserProfile()

    if not isinstance(data, dict):
        return UserProfile()

    return UserProfile(
        unit_types=_clean_list(data.get("unit_types")),
        budgets=_clean_list(data.get("budgets")),
        projects=_clean_list(data.get("projects")),
        topics=_clean_list(data.get("topics")),
    )


def remember(key: str, question: str, project_id: str | None = None, db: Session | None = None) -> None:
    """Fold one question into the stored profile. Never raises.

    Read-modify-write, not atomic — two concurrent questions could drop one update, which
    costs a remembered preference and nothing more. `db` recovers the project from the
    question when the session carries none, the normal case (see `_resolve_project`).
    """
    remember_many(key, [question], project_id, db)


def remember_many(
    key: str,
    questions: list[str],
    project_id: str | None = None,
    db: Session | None = None,
) -> None:
    """Fold several oldest-to-newest human questions into one profile and one write.

    Used to backfill a newly session-scoped Sales profile from that session's own MySQL
    transcript. It never reads the legacy Sale-wide key, which may contain several end
    customers. One Redis write keeps this rare migration path cheap even for a long chat.
    """
    client = get_redis_client()
    usable = [question for question in questions if question and question.strip()]
    if client is None or not usable:
        return

    try:
        merged = load_profile(key)
        for question in usable:
            extracted = extract_facts(question)
            extracted.projects = _resolve_projects(question, project_id, db)
            if not extracted.is_empty():
                merged = _merge(merged, extracted)

        if merged.is_empty():
            return
        _save_profile(client, key, merged)
    except Exception:
        logger.warning(
            "Ghi ho so ghi nho that bai; cau tra loi khong bi anh huong.",
            exc_info=True,
            extra={"event": "memory.remember.failed", "key": key},
        )


def _save_profile(client, key: str, profile: UserProfile) -> None:
    client.set(
        key,
        json.dumps(
            {
                "unit_types": profile.unit_types,
                "budgets": profile.budgets,
                "projects": profile.projects,
                "topics": profile.topics,
            },
            ensure_ascii=False,
        ),
        ex=get_settings().memory_ttl_seconds,
    )


def forget(key: str) -> None:
    """Delete a profile outright — the customer's "quen toi di" / privacy request."""
    client = get_redis_client()
    if client is None:
        return

    try:
        client.delete(key)
    except Exception:
        logger.warning(
            "Xoa ho so ghi nho that bai.",
            exc_info=True,
            extra={"event": "memory.forget.failed", "key": key},
        )


def _resolve_project(question: str, project_id: str | None, db: Session | None) -> str | None:
    """Which project this question is about: the session's, else the one it names.

    The session's `project_id` wins when set, but it's almost never set — the picker was
    dropped from session creation — so without this fallback `projects` stayed permanently
    empty. Imported inside the function to keep the module importable without a database.
    """
    if project_id:
        return project_id
    if db is None:
        return None

    from backend.services.answer_images_service import resolve_project_id

    return resolve_project_id(db, question)


def _resolve_projects(question: str, project_id: str | None, db: Session | None) -> list[str]:
    """All projects named in one question, or the session's explicit project.

    Comparison questions frequently name two subdivisions; storing only the single best
    match makes a later "khách quan tâm phân khu nào?" silently omit half the request.
    """
    if project_id:
        return [project_id]
    if db is None:
        return []

    from backend.services.answer_images_service import resolve_project_ids

    return resolve_project_ids(db, question)


def extract_facts(question: str, project_id: str | None = None) -> UserProfile:
    """Pull durable preferences out of one question.

    Deliberately conservative regex rather than an LLM call: this runs on every message,
    so an extra model round-trip here would spend tokens and latency on every single
    turn to learn something as small as "this person asks about 2PN". Missing a
    preference is cheap; inventing one is not — which is why `_extract_budgets` requires
    the sentence to actually be about affordability before recording a figure.
    """
    if not question or not question.strip():
        return UserProfile()

    unit_types: list[str] = []
    for match in UNIT_TYPE_PATTERN.finditer(question):
        token = re.sub(r"\s+", "", match.group(0)).upper()
        if token not in unit_types:
            unit_types.append(token)

    budgets = _extract_budgets(question)

    projects = [project_id] if project_id else []

    return UserProfile(unit_types=unit_types, budgets=budgets, projects=projects)


def _extract_budgets(question: str) -> list[str]:
    """Money figures that are this person's budget, not a price they asked about.

    Three gates, each earning its place:

    1. The sentence must actually talk about affordability ("ngân sách", "tầm giá",
       "muốn mua"). A bare figure is far more often a price being asked about.
    2. A price question wins outright. "Ngân sách 3 tỷ thì căn 5 tỷ có hợp không?" is
       about a 5 tỷ unit *and* a 3 tỷ budget, and picking the wrong one is worse than
       picking neither — so an explicit price question means nothing is stored.
    3. At most one figure. A sentence carrying several money figures is comparing units,
       not stating one budget.
    """
    if not BUDGET_CONTEXT_PATTERN.search(question) or PRICE_QUESTION_PATTERN.search(question):
        return []

    range_match = BUDGET_RANGE_PATTERN.search(question)
    if range_match:
        low, high, unit = range_match.groups()
        return [f"{low} - {high} {unit.lower()}"]

    found: list[str] = []
    for number, unit in BUDGET_PATTERN.findall(question):
        token = f"{number} {unit.lower()}"
        if token not in found:
            found.append(token)

    return found if len(found) == 1 else []


def format_profile(profile: UserProfile) -> str:
    """Render a profile for the prompt. Empty profile renders as an empty string."""
    if profile.is_empty():
        return ""

    lines = []
    if profile.unit_types:
        lines.append(f"- Loại căn thường quan tâm: {', '.join(profile.unit_types)}")
    if profile.budgets:
        lines.append(f"- Mức giá từng nhắc tới: {', '.join(profile.budgets)}")
    if profile.projects:
        lines.append(f"- Dự án từng hỏi: {', '.join(_display_project(item) for item in profile.projects)}")
    if profile.topics:
        lines.append(f"- Chủ đề hay hỏi: {', '.join(profile.topics)}")
    return "\n".join(lines)


def format_recall_answer(query: str, profile: UserProfile) -> str:
    """Answer a customer's-profile recall without RAG or an LLM call."""
    if profile.is_empty():
        return (
            "Mình chưa ghi nhận đủ nhu cầu của khách trong phiên này. "
            "Anh/chị có thể bổ sung phân khu, loại căn hoặc khoảng tài chính khách đang quan tâm."
        )

    normalized = strip_diacritics(query)
    asks_project = any(term in normalized for term in ("phan khu", "du an", "quan tam den dau"))
    asks_budget = any(term in normalized for term in ("ngan sach", "tai chinh", "tam gia", "bao nhieu tien"))
    asks_unit = any(term in normalized for term in ("loai can", "can gi", "may phong", "phong ngu"))

    lines: list[str] = []
    if profile.projects and (asks_project or not (asks_budget or asks_unit)):
        projects = ", ".join(_display_project(item) for item in profile.projects)
        lines.append(f"- Phân khu/dự án từng quan tâm: {projects}.")
    if profile.unit_types and (asks_unit or not (asks_project or asks_budget)):
        lines.append(f"- Loại căn từng quan tâm: {', '.join(profile.unit_types)}.")
    if profile.budgets and (asks_budget or not (asks_project or asks_unit)):
        lines.append(f"- Khoảng tài chính từng đề cập: {', '.join(profile.budgets)}.")
    if profile.topics and not (asks_project or asks_budget or asks_unit):
        lines.append(f"- Chủ đề thường hỏi: {', '.join(profile.topics)}.")

    if not lines:
        return "Mình chưa ghi nhận thông tin đó trong phiên khách hàng này."
    return "Dựa trên trao đổi trong riêng phiên này, khách đang có các mối quan tâm sau:\n" + "\n".join(lines)


def _display_project(project_id: str) -> str:
    """Turn a catalogue slug into a readable label without another database query."""
    return " ".join(part.capitalize() for part in project_id.replace("_", "-").split("-") if part)


def _merge(current: UserProfile, extracted: UserProfile) -> UserProfile:
    """Newest first, de-duplicated, capped — so a profile tracks recent interest.

    Order matters: a customer who moved from 2PN to 3PN should have 3PN read first, and
    once the cap is reached the oldest interest is the one that falls off.
    """
    return UserProfile(
        unit_types=_bounded(extracted.unit_types, current.unit_types),
        budgets=_bounded(extracted.budgets, current.budgets),
        projects=_bounded(extracted.projects, current.projects),
        topics=_bounded(extracted.topics, current.topics),
    )


def _bounded(new_items: list[str], old_items: list[str]) -> list[str]:
    merged = list(new_items)
    for item in old_items:
        if item not in merged:
            merged.append(item)
    return merged[:MAX_ITEMS_PER_FIELD]


def _clean_list(value: object) -> list[str]:
    """Coerce whatever was stored into a list of non-empty strings.

    Defensive because the value may have been written by an older version of this code,
    or hand-edited in redis-cli during debugging.
    """
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()][:MAX_ITEMS_PER_FIELD]
