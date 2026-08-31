"""Reflection memory — lessons the agent learned from its own mistakes.

The Reflexion loop in `agent_pipeline` corrects a rejected draft *within* one question,
then forgets everything — the next question repeats the mistake and pays for the same
extra Gemini call. This module is the missing half: a Verifier rejection distills the
defect into one lesson, stored so later similar questions get it in their prompt *before*
generating.

Deliberately not chat history — a lesson is three short fields (trigger, lesson, fix), the
compressed form; storing the failed conversation instead would grow unbounded and make
every later prompt noisier for no gain.

Accepts an optional scope. Sale consultation chat always supplies a session scope, since
one session is one end customer and corrections must not cross to another. Callers that
omit it use the legacy global store. Fails open like `memory_service`: no Redis or a
corrupt value means no lesson, never a failed answer.
"""

import json
import logging
import time
from dataclasses import dataclass

from backend.core.config import get_settings
from backend.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

_KEY = "reflection:lessons"


def sale_session_scope(session_id: int) -> str:
    """Stable reflection namespace for one customer's Sale consultation session."""
    return f"sale-session:{session_id}"


def _storage_key(scope: str | None = None) -> str:
    """Redis key for a reflection scope; no scope preserves legacy global behaviour."""
    return _KEY if not scope else f"{_KEY}:{scope}"


MAX_LESSONS = 12

MAX_LESSONS_PER_PROMPT = 2

_MIN_TRIGGER_OVERLAP = 2

_PUNCTUATION = "?!.,;:()[]{}\"'“”‘’…-–—/\\"

_STOPWORDS = frozenset(
    """
    la cua co khong duoc va hay thi mot cac nhung o tai voi cho ve tu den nhu
    bao nhieu the nao gi sao a anh chi em minh toi ban day do nay kia
    du an can nha vinhomes
    """.split()  # noqa: SIM905 - multiline source is easier to review than a long literal list
)


@dataclass(frozen=True)
class Lesson:
    """One mistake and how to avoid repeating it."""

    trigger: str
    lesson: str
    fix: str
    failure_mode: str
    hits: int = 1
    updated_at: float = 0.0

    def render(self) -> str:
        return f"- Khi {self.trigger}: {self.lesson} ({self.fix})"


def load_lessons(scope: str | None = None) -> list[Lesson]:
    """Every stored lesson. Any failure yields an empty list."""
    client = get_redis_client()
    if client is None:
        return []

    try:
        raw = client.get(_storage_key(scope))
    except Exception:
        logger.warning(
            "Doc reflection memory that bai; coi nhu chua co bai hoc nao.",
            exc_info=True,
            extra={"event": "reflection.load.failed"},
        )
        return []

    if not raw:
        return []

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        logger.warning("Reflection memory hong; bo qua.", extra={"event": "reflection.load.corrupt"})
        return []

    if not isinstance(data, list):
        return []

    lessons = []
    for item in data:
        if not isinstance(item, dict):
            continue
        trigger = str(item.get("trigger") or "").strip()
        lesson_text = str(item.get("lesson") or "").strip()
        if not trigger or not lesson_text:
            continue
        lessons.append(
            Lesson(
                trigger=trigger,
                lesson=lesson_text,
                fix=str(item.get("fix") or "").strip(),
                failure_mode=str(item.get("failure_mode") or "").strip(),
                hits=int(item.get("hits") or 1),
                updated_at=float(item.get("updated_at") or 0.0),
            )
        )
    return lessons


def record_lesson(*, query: str, failure_mode: str, feedback: str, scope: str | None = None) -> None:
    """Distil one Verifier rejection into a lesson and store it. Never raises.

    Called after a rejection, off the answer's critical path — the Sale already has their
    response by the time this runs, so a slow or failed write costs nothing they see.
    """
    client = get_redis_client()
    if client is None or not feedback.strip() or not failure_mode or failure_mode == "none":
        return

    trigger = _trigger_from(query)
    if not trigger:
        return

    try:
        lessons = load_lessons(scope)
        merged = _merge(lessons, _build(trigger, failure_mode, feedback))
        client.set(
            _storage_key(scope),
            json.dumps([_as_dict(item) for item in merged], ensure_ascii=False),
            ex=get_settings().reflection_ttl_seconds,
        )
    except Exception:
        logger.warning(
            "Ghi reflection memory that bai; cau tra loi khong bi anh huong.",
            exc_info=True,
            extra={"event": "reflection.record.failed", "failure_mode": failure_mode},
        )


def relevant_lessons(
    query: str,
    limit: int = MAX_LESSONS_PER_PROMPT,
    scope: str | None = None,
) -> list[Lesson]:
    """Lessons worth putting in this question's prompt, most useful first.

    Matched on trigger-word overlap rather than embeddings: this runs before every
    generation, and an embedding call here would add latency and cost to every question
    to rank at most a dozen short strings. Overlap is crude but it is the difference
    between a relevant lesson and none at all, and an irrelevant lesson that slips
    through costs one line of prompt.
    """
    words = _keywords(query)
    if not words:
        return []

    scored = []
    for lesson in load_lessons(scope):
        overlap = len(words & _keywords(lesson.trigger))
        if overlap >= _MIN_TRIGGER_OVERLAP:
            scored.append((overlap, lesson.hits, lesson))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return [lesson for _, _, lesson in scored[:limit]]


def format_lessons(lessons: list[Lesson]) -> str:
    """Render lessons for the prompt. No lessons renders as an empty string."""
    return "\n".join(lesson.render() for lesson in lessons)


def forget_all(scope: str | None = None) -> None:
    """Drop every lesson — the Admin "start over" after reworking prompts or documents."""
    client = get_redis_client()
    if client is None:
        return

    try:
        client.delete(_storage_key(scope))
    except Exception:
        logger.warning("Xoa reflection memory that bai.", exc_info=True, extra={"event": "reflection.forget.failed"})


def _build(trigger: str, failure_mode: str, feedback: str) -> Lesson:
    """Turn one rejection into a lesson.

    The `fix` is derived from the failure mode rather than from the judge's sentence: the
    feedback names what went wrong *this time* ("thiếu tiến độ thanh toán"), while the fix
    has to generalise to the next question of the same shape.
    """
    return Lesson(
        trigger=trigger,
        lesson=_condense(feedback),
        fix=_FIX_BY_MODE.get(failure_mode, ""),
        failure_mode=failure_mode,
        hits=1,
        updated_at=time.time(),
    )


_FIX_BY_MODE = {
    "hallucinated-fact": "chỉ nêu con số có trong ngữ cảnh, không suy diễn",
    "incomplete-answer": "trả lời đủ từng ý của câu hỏi trước khi dừng",
    "off-topic": "bám đúng điều được hỏi",
    "missing-evidence": "nói thẳng là chưa có dữ liệu thay vì lấp chỗ trống",
    "unsupported-commitment": "không hứa hẹn thay chủ đầu tư",
}


def _condense(feedback: str, limit: int = 120) -> str:
    """One sentence, capped. A lesson that needs a paragraph is not a lesson."""
    first = feedback.strip().split(".")[0].strip()
    if not first:
        first = feedback.strip()
    return first if len(first) <= limit else first[:limit].rstrip() + "…"


def _trigger_from(query: str, max_words: int = 6) -> str:
    """The shape of question this lesson applies to, as its distinctive words."""
    words = [word for word in _tokenise(query) if word not in _STOPWORDS]
    return " ".join(words[:max_words])


def _keywords(text: str) -> set[str]:
    return {word for word in _tokenise(text) if word not in _STOPWORDS}


def _tokenise(text: str) -> list[str]:
    """Lowercased words, accents folded, so "chính sách" and "chinh sach" match.

    Punctuation is stripped from each word rather than used to reject it — filtering on
    `word.isalnum()` silently dropped the LAST word of every query ending in "?", so "Giá
    căn 2PN The Palma?" lost "palma" and two different projects' lessons looked identical
    to `_merge`.
    """
    from backend.utils.text import strip_diacritics

    words = (word.strip(_PUNCTUATION) for word in strip_diacritics(text).lower().split())
    return [word for word in words if word.isalnum() and len(word) > 1]


def _merge(existing: list[Lesson], new: Lesson) -> list[Lesson]:
    """Fold a new lesson in, reinforcing an equivalent one rather than duplicating it.

    Sameness is judged on the trigger alone, NOT `failure_mode` — the Verifier labels the
    same defect inconsistently between runs (`gia 2pn con` was seen stored once as
    `incomplete-answer`, once as `missing-evidence`, carrying an identical lesson), which
    could otherwise take both `MAX_LESSONS_PER_PROMPT` slots to say one thing.
    """
    merged = []
    reinforced = False

    for lesson in existing:
        same_shape = _keywords(lesson.trigger) == _keywords(new.trigger)
        if same_shape and not reinforced:
            merged.append(
                Lesson(
                    trigger=lesson.trigger,
                    lesson=lesson.lesson,
                    fix=lesson.fix or new.fix,
                    failure_mode=lesson.failure_mode,
                    hits=lesson.hits + 1,
                    updated_at=new.updated_at,
                )
            )
            reinforced = True
        else:
            merged.append(lesson)

    if not reinforced:
        merged.insert(0, new)

    merged.sort(key=lambda item: (item.hits, item.updated_at), reverse=True)
    return merged[:MAX_LESSONS]


def _as_dict(lesson: Lesson) -> dict:
    return {
        "trigger": lesson.trigger,
        "lesson": lesson.lesson,
        "fix": lesson.fix,
        "failure_mode": lesson.failure_mode,
        "hits": lesson.hits,
        "updated_at": lesson.updated_at,
    }
