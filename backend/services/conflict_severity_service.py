"""Deterministic business severity for document-conflict alerts.

Severity is derived from persisted detector evidence instead of presentation-layer
guesswork. This makes legacy and newly-created flags use the same classification without
requiring a database backfill.
"""

from __future__ import annotations

from typing import Any, Literal

ConflictSeverity = Literal["low", "medium", "high"]

_HIGH_IMPACT_TYPE_TOKENS = frozenset(
    {
        "price",
        "payment",
        "legal",
        "fee",
        "discount",
        "promotion",
        "inventory",
        "availability",
        "handover",
        "deadline",
        "penalty",
        "interest",
        "tax",
        "vat",
        "policy",
        "eligibility",
    }
)


def classify_conflict_severity(
    *,
    detection_method: str,
    confidence: float | None,
    conflict_type: str | None,
    evidence: dict[str, Any] | None,
) -> ConflictSeverity:
    """Classify an open conflict as low, medium or high business risk.

    Uncertain semantic judgements remain low priority regardless of model confidence.
    Confirmed high-impact facts and highly-confident contradictions are high priority;
    other grounded or deterministic conflicts are medium priority.
    """

    evidence = evidence if isinstance(evidence, dict) else {}
    semantic = evidence.get("semantic")
    semantic = semantic if isinstance(semantic, dict) else {}
    rule = evidence.get("rule")
    rule = rule if isinstance(rule, dict) else {}

    decision = semantic.get("decision")
    if decision == "uncertain":
        return "low"

    semantic_confidence = semantic.get("confidence")
    measured_confidence = confidence
    if isinstance(semantic_confidence, (int, float)):
        measured_confidence = max(measured_confidence or 0.0, float(semantic_confidence))

    normalized_type = (conflict_type or semantic.get("conflict_type") or "").casefold()
    type_tokens = {token for token in normalized_type.replace("-", "_").split("_") if token}
    is_high_impact = bool(type_tokens & _HIGH_IMPACT_TYPE_TOKENS)
    has_price_difference = bool(rule.get("price_differences"))
    has_fact_difference = bool(rule.get("fact_differences"))

    if decision == "conflict":
        if is_high_impact or has_price_difference or (measured_confidence or 0.0) >= 0.85:
            return "high"
        return "medium"

    if has_price_difference or is_high_impact:
        return "high"
    if has_fact_difference or detection_method in {"rule", "hybrid"}:
        return "medium"
    if (measured_confidence or 0.0) >= 0.75:
        return "medium"
    return "low"
