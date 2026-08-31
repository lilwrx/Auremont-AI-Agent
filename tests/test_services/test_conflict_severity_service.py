import pytest

from backend.services.conflict_severity_service import classify_conflict_severity


@pytest.mark.parametrize(
    ("expected", "detection_method", "confidence", "conflict_type", "evidence"),
    [
        (
            "low",
            "llm",
            0.98,
            "policy_terms",
            {"semantic": {"decision": "uncertain", "confidence": 0.98}},
        ),
        (
            "medium",
            "llm",
            0.78,
            "document_change",
            {"semantic": {"decision": "conflict", "confidence": 0.78}},
        ),
        (
            "high",
            "llm",
            0.95,
            "policy_terms",
            {"semantic": {"decision": "conflict", "confidence": 0.95}},
        ),
        (
            "high",
            "rule",
            None,
            "price",
            {"rule": {"price_differences": [{"fact_key": "unit.price"}]}},
        ),
        ("medium", "rule", None, "document_change", None),
        ("low", "llm", 0.55, None, None),
    ],
)
def test_conflict_severity_is_derived_from_grounded_business_risk(
    expected,
    detection_method,
    confidence,
    conflict_type,
    evidence,
):
    assert (
        classify_conflict_severity(
            detection_method=detection_method,
            confidence=confidence,
            conflict_type=conflict_type,
            evidence=evidence,
        )
        == expected
    )
