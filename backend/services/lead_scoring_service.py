"""Lead scoring — how ready a customer is to buy, so a Sale knows who to call first.

Hard signals are scored by deterministic rules, not an LLM. This runs on the path of every
single customer turn (including the ones that never reach the agent pipeline), has to fit
inside a turn already spending two Gemini calls, and must keep working when Gemini is down —
a scoring outage that silently demoted every lead to COLD would hide the queue rather than
degrade it. The LLM is confined to `enrich_with_llm`, which reads the two soft judgements no
regex can make: how urgent the person sounds, and whether they are buying to live in or to
invest.

The hybrid is enforced structurally, not by convention: `SOFT_MAX` sits below
`Settings.lead_warm_threshold`, so a lead with no hard signal at all can never be lifted past
COLD by the model, and can never reach HOT.

Budget detection deliberately goes through `memory_service.extract_facts` rather than reading
a `price` constraint off `SearchCriteria`. The two extractors answer different questions:
`SearchCriteria` records any price the sentence mentions, so "tầm 3.5 tỷ" — a real budget,
phrased the way most Vietnamese buyers phrase it — arrives as `Source.INFERRED` and would be
dropped by an EXPLICIT-only filter, while `memory_service` runs the budget-context /
price-question gate written for exactly this distinction.

To retune the weights, edit `_RULE_WEIGHTS` and bump `ANALYSIS_VERSION`; the signatures do not
change, and rows scored under old weights stay identifiable in the Admin averages.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, field_validator

from backend.ai import intent
from backend.core.enums import LeadPurpose, LeadTier, LeadUrgency
from backend.core.gemini_client import generate_json
from backend.services import memory_service, search_criteria

logger = logging.getLogger(__name__)

ANALYSIS_VERSION = "rules-3"

_RULE_WEIGHTS: dict[str, int] = {
    "transaction_ready": 45,
    "consideration_intent": 25,
    "stated_budget": 30,
    "named_unit_code": 20,
    "three_filters": 8,
    "criteria_known": 5,
    "closing_intent": 15,
    "wants_human": 10,
    "near_term_timeline": 10,
    "has_phone": 10,
    "engaged": 5,
    "purpose_known": 3,
    "household_known": 2,
}

MAX_SCORE = 100
SOFT_MAX = 20
PROFILE_MAX = 35

_INTENT_SIGNALS = ("transaction_ready", "consideration_intent", "closing_intent", "wants_human")
_PROFILE_SIGNALS = (
    "stated_budget",
    "named_unit_code",
    "three_filters",
    "criteria_known",
    "purpose_known",
    "household_known",
)

LATCHING_SIGNALS = (
    "transaction_ready",
    "stated_budget",
    "named_unit_code",
    "near_term_timeline",
)
_LEGACY_SAFE_SIGNALS = ("stated_budget", "named_unit_code")

_ENGAGED_TURNS = 6
_MIN_FILTERS = 3

_CLAUSE_SPLIT = re.compile(r"[,;\n]+|(?<=[a-zA-ZÀ-ỹ])[!?]+")


def _stated_budgets(query: str) -> list[str]:
    """Budgets the person stated about themselves, read clause by clause."""
    found: list[str] = []
    for clause in _CLAUSE_SPLIT.split(query):
        if clause and clause.strip():
            found.extend(memory_service.extract_facts(clause).budgets)
    return found


@dataclass(frozen=True)
class LeadSignals:
    """One turn's deterministic evidence. Nothing here calls an LLM or touches a database."""

    flags: dict[str, bool] = field(default_factory=dict)
    turn_count: int = 0
    newly_latched: tuple[str, ...] = ()

    def fired(self, name: str) -> bool:
        return bool(self.flags.get(name))


class LeadSoftSignals(BaseModel):
    """The LLM's read of tone and timing.

    Every field is defaulted: a model that omits one must not invalidate the other four, same
    reasoning as `VerifierResult`. Unknown labels degrade DOWNWARD (to EXPLORING / UNKNOWN)
    rather than upward — an unreadable verdict must never be the reason a Sale drops a real
    customer to chase a lead the model invented.
    """

    urgency: LeadUrgency = LeadUrgency.EXPLORING
    purpose: LeadPurpose = LeadPurpose.UNKNOWN
    decision_ready: bool = False
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.0
        if number > 1.0:
            number = number / 100 if number <= 100 else 1.0
        return min(max(number, 0.0), 1.0)

    @field_validator("urgency", mode="before")
    @classmethod
    def _coerce_urgency(cls, value: Any) -> Any:
        try:
            return LeadUrgency(str(value).strip().lower())
        except ValueError:
            return LeadUrgency.EXPLORING

    @field_validator("purpose", mode="before")
    @classmethod
    def _coerce_purpose(cls, value: Any) -> Any:
        try:
            return LeadPurpose(str(value).strip().lower())
        except ValueError:
            return LeadPurpose.UNKNOWN

    @field_validator("reason", mode="before")
    @classmethod
    def _coerce_reason(cls, value: Any) -> str:
        return str(value).strip()[:300] if value is not None else ""


@dataclass(frozen=True)
class LeadVerdict:
    """What gets written to the `leads` row."""

    tier: LeadTier
    score: int
    rule_score: int
    soft_score: int | None
    urgency: LeadUrgency | None
    purpose: LeadPurpose | None
    confidence: float | None
    signals: dict[str, Any]
    detection_method: str
    reason: str


def compatible_latched_flags(flags: dict[str, bool] | None, analysis_version: str | None) -> dict[str, bool]:
    """Keep only stable facts when a lead was scored by an older rule vocabulary."""
    stored = dict(flags or {})
    if analysis_version == ANALYSIS_VERSION:
        return stored
    return {name: True for name in _LEGACY_SAFE_SIGNALS if stored.get(name)}


def collect_signals(
    query: str,
    criteria: search_criteria.SearchCriteria,
    *,
    latched: dict[str, bool] | None = None,
    turn_count: int = 0,
    is_registered: bool = False,
    has_phone: bool = False,
) -> LeadSignals:
    """Read this turn's hard signals, folded together with everything latched earlier."""
    previous = dict(latched or {})
    flags: dict[str, bool] = {}

    budgets = _stated_budgets(query)
    flags["stated_budget"] = bool(budgets)

    flags["transaction_ready"] = intent.is_transaction_ready_lead(query)
    flags["consideration_intent"] = intent.is_consideration_lead(query)
    flags["closing_intent"] = intent.needs_registration_gate(query)
    flags["wants_human"] = intent.wants_human_agent(query)
    flags["near_term_timeline"] = intent.has_near_term_timeline(query)
    flags["named_unit_code"] = criteria.get(search_criteria.FIELD_UNIT_CODES) is not None

    filter_count = len(criteria.filtering())
    flags["criteria_known"] = filter_count > 0
    flags["three_filters"] = filter_count >= _MIN_FILTERS
    flags["purpose_known"] = criteria.purpose is not None
    flags["household_known"] = criteria.household_size is not None

    flags["registered"] = is_registered
    flags["has_phone"] = has_phone
    flags["engaged"] = turn_count >= _ENGAGED_TURNS

    newly_latched = tuple(name for name in LATCHING_SIGNALS if flags.get(name) and not previous.get(name))
    for name in LATCHING_SIGNALS:
        flags[name] = flags.get(name, False) or previous.get(name, False)

    return LeadSignals(flags=flags, turn_count=turn_count, newly_latched=newly_latched)


def score_rules(signals: LeadSignals) -> int:
    return min(sum(_rule_contributions(signals).values()), MAX_SCORE)


def _rule_contributions(signals: LeadSignals) -> dict[str, int]:
    """Return non-overlapping points so one sentence cannot score the same intent repeatedly."""
    contributions: dict[str, int] = {}

    fired_intents = [name for name in _INTENT_SIGNALS if signals.fired(name)]
    if fired_intents:
        strongest = max(fired_intents, key=_RULE_WEIGHTS.__getitem__)
        contributions[strongest] = _RULE_WEIGHTS[strongest]

    remaining_profile = PROFILE_MAX
    for name in _PROFILE_SIGNALS:
        if not signals.fired(name) or remaining_profile <= 0:
            continue
        points = min(_RULE_WEIGHTS[name], remaining_profile)
        contributions[name] = points
        remaining_profile -= points

    for name in ("near_term_timeline", "has_phone", "engaged"):
        if signals.fired(name):
            contributions[name] = _RULE_WEIGHTS[name]

    return contributions


def signals_from_stored(
    flags: dict[str, bool] | None, *, turn_count: int = 0, is_registered: bool = False, has_phone: bool = False
) -> LeadSignals:
    """Rebuild signals from what was already stored, updating only the identity flags.

    Used when someone registers: no new sentence was said, but they stopped being anonymous
    and handed over a phone number. Handing over contact details IS the moment a lead becomes
    reachable, so waiting for their next message to reflect it would show the Sale a stale
    badge at exactly the point they most want to act on it.
    """
    updated = dict(flags or {})
    updated.pop("budget_over_1bn", None)
    updated["registered"] = is_registered
    updated["has_phone"] = has_phone
    updated["engaged"] = turn_count >= _ENGAGED_TURNS
    return LeadSignals(flags=updated, turn_count=turn_count)


def classify(
    score: int,
    signals: LeadSignals,
    soft: LeadSoftSignals | None = None,
    *,
    hot_threshold: int,
    warm_threshold: int,
) -> LeadTier:
    """Classify readiness with prerequisites, not a threshold alone.

    HOT requires a reachable person, an explicit commitment action, and one qualifying
    detail. A high numeric score without those prerequisites is intentionally capped at WARM.
    """
    has_timing = soft is not None and soft.urgency in {LeadUrgency.IMMEDIATE, LeadUrgency.NEAR_TERM}
    has_qualification = (
        any(signals.fired(name) for name in ("stated_budget", "named_unit_code", "three_filters", "near_term_timeline"))
        or has_timing
    )
    hot_eligible = signals.fired("has_phone") and signals.fired("transaction_ready") and has_qualification

    if score >= hot_threshold and hot_eligible:
        return LeadTier.HOT
    if score >= warm_threshold or signals.fired("consideration_intent") or signals.fired("transaction_ready"):
        return LeadTier.WARM
    return LeadTier.COLD


def should_enrich(
    rule_score: int,
    signals: LeadSignals,
    *,
    turns_since_llm: int | None,
    hot_threshold: int,
    warm_threshold: int,
    min_turns: int,
) -> bool:
    """True only inside the decision band, where the model can still change the verdict.

    Below WARM the soft cap makes a tier change arithmetically impossible; at or above HOT the
    lead is already top priority and there is nothing left to buy. That single rule removes
    most calls; the turn gap removes most of the rest. A newly latched hard signal overrides
    the gap, because that is exactly the turn on which the answer changes.
    """
    if not (warm_threshold <= rule_score < hot_threshold):
        return False
    if signals.newly_latched:
        return True
    return turns_since_llm is None or turns_since_llm >= min_turns


_SYSTEM_INSTRUCTION = (
    "Bạn đọc tin nhắn của một khách hàng bất động sản và chỉ đánh giá hai điều: mức độ gấp về "
    "thời gian, và mục đích mua. Chỉ dựa vào điều khách đã nói, tuyệt đối không suy diễn. "
    "Không chắc thì trả về urgency='exploring', purpose='unknown', confidence thấp."
)

_PROMPT = """Các tin nhắn gần nhất của khách (chỉ lời khách, không có lời tư vấn viên):
{turns}

Trả về JSON:
- urgency: "immediate" (nói rõ cần gấp, trong tuần/tháng này), "near_term" (có mốc thời gian nhưng chưa gấp), "exploring" (chưa nói gì về thời gian)
- purpose: "living" (để ở), "investment" (đầu tư/cho thuê), "business" (kinh doanh), "unknown"
- decision_ready: true nếu khách đã nói tới xuống tiền, đi xem nhà thật, hoặc pháp lý cụ thể
- confidence: 0.0-1.0, mức chắc chắn của bạn
- reason: MỘT câu tiếng Việt, trích đúng điều khách đã nói
"""


def enrich_with_llm(customer_turns: list[str]) -> LeadSoftSignals | None:
    """Soft signals, or None when the model gave nothing usable.

    None means "the rules stand alone", NOT a zero score — unlike the Verifier, failing closed
    here would empty the Sale's queue during a Gemini outage.
    """
    if not customer_turns:
        return None
    try:
        return generate_json(
            _PROMPT.format(turns="\n".join(f"- {turn}" for turn in customer_turns)),
            LeadSoftSignals,
            system_instruction=_SYSTEM_INSTRUCTION,
        )
    except Exception:
        logger.warning("Lead soft-signal pass failed; keeping the rule score.", exc_info=True)
        return None


def _soft_points(soft: LeadSoftSignals) -> int:
    raw = 0
    if soft.urgency == LeadUrgency.IMMEDIATE:
        raw += 15
    elif soft.urgency == LeadUrgency.NEAR_TERM:
        raw += 8
    if soft.decision_ready:
        raw += 5
    return min(int(raw * soft.confidence), SOFT_MAX)


def combine(
    rule_score: int,
    signals: LeadSignals,
    soft: LeadSoftSignals | None,
    *,
    hot_threshold: int,
    warm_threshold: int,
) -> LeadVerdict:
    soft_points = _soft_points(soft) if soft is not None else None
    total = min(rule_score + (soft_points or 0), MAX_SCORE)
    return LeadVerdict(
        tier=classify(total, signals, soft, hot_threshold=hot_threshold, warm_threshold=warm_threshold),
        score=total,
        rule_score=rule_score,
        soft_score=soft_points,
        urgency=soft.urgency if soft is not None else None,
        purpose=soft.purpose if soft is not None else None,
        confidence=soft.confidence if soft is not None else None,
        signals={
            "flags": signals.flags,
            "weights": _rule_contributions(signals),
            "analysis_version": ANALYSIS_VERSION,
            **({"llm_reason": soft.reason} if soft is not None and soft.reason else {}),
        },
        detection_method="rule+llm" if soft is not None else "rule",
        reason=soft.reason if soft is not None else "",
    )


def suggest_next_action(
    tier: LeadTier, *, has_phone: bool, has_budget: bool, wants_human: bool, turn_count: int
) -> str:
    """One concrete thing for the Sale to do next, given the tier and what is already known.

    Advice, not automation — the Sale decides. Kept here rather than in the router because
    it reads the same signal vocabulary the scorer writes, and because a wrong suggestion on
    a HOT lead is a real cost worth covering with tests.

    Ordered by what is MISSING, not by tier alone: a HOT lead with no phone number needs the
    number before anything else, and telling a Sale to "call now" when there is nothing to
    dial is worse than saying nothing.
    """
    if not has_phone:
        return "Chưa có số điện thoại — xin số để chuyên viên gọi lại xác nhận nhu cầu."
    if tier is LeadTier.HOT:
        if wants_human:
            return "Khách đã chủ động xin gặp người thật — nên gọi ngay trong vài phút tới."
        return "Lead nóng, đã có số — gọi sớm để chốt lịch xem nhà trước khi khách nguội."
    if tier is LeadTier.WARM:
        if not has_budget:
            return "Hỏi rõ ngân sách và thời điểm dự kiến mua để xếp đúng nhóm căn."
        return "Đã biết ngân sách — gửi 2-3 căn khớp nhất rồi mời đi xem thực tế."
    if turn_count <= 1:
        return "Khách mới bắt đầu tìm hiểu — hỏi nhu cầu ở hay đầu tư để định hướng tư vấn."
    return "Khách chưa để lộ nhu cầu rõ — gợi ý vài phân khu tiêu biểu xem phản ứng."
