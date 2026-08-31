"""Regression guard for failures that used to be completely invisible.

Every test asserts **two** things: the return value is unchanged (the recovery
behaviour these call sites deliberately implement) *and* a record was emitted.
The first half is what stops a future "improvement" from turning a graceful
degradation into a 500 in front of a customer.
"""

import logging

import pytest

from backend.services import cache_service, verifier_service
from backend.services.agent_pipeline import GENERATION_ERROR_MESSAGE, run_pipeline
from backend.services.inventory_service import _parse_unit, _to_float


class _SimulatedError(Exception):
    pass


def _raise(*args, **kwargs):
    raise _SimulatedError("simulated infrastructure failure")


def test_cache_lookup_failure_is_logged_and_returns_a_miss(monkeypatch, caplog):
    monkeypatch.setattr(cache_service, "get_qdrant_client", _raise)

    with caplog.at_level(logging.WARNING, logger="backend.services.cache_service"):
        result = cache_service.lookup_cache("gia can 2PN?", "ocean-park-3")

    assert result is None
    record = next(r for r in caplog.records if getattr(r, "event", None) == "cache.lookup.failed")
    assert record.project_id == "ocean-park-3"
    assert record.exc_info is not None


def test_cache_store_failure_is_logged_and_swallowed(monkeypatch, caplog):
    monkeypatch.setattr(cache_service, "_ensure_cache_collection", _raise)

    with caplog.at_level(logging.WARNING, logger="backend.services.cache_service"):
        assert cache_service.store_cache("q", "a", [], 0.9, "ocean-park-3") is None

    assert any(getattr(r, "event", None) == "cache.store.failed" for r in caplog.records)


def test_judge_failure_is_logged_at_error_and_still_fails_closed(monkeypatch, caplog):
    """A broken Verifier and a bad answer both score 0.0 - only the log separates them."""
    monkeypatch.setattr(verifier_service, "generate_json", _raise)

    with caplog.at_level(logging.ERROR, logger="backend.services.verifier_service"):
        result = verifier_service.score_answer("gia?", "3.6 ty", ["context"])

    assert result.score == 0.0
    record = next(r for r in caplog.records if getattr(r, "event", None) == "verifier.judge.failed")
    assert record.levelno == logging.ERROR
    assert record.exc_info is not None


def test_a_judge_with_no_verdict_is_logged_and_fails_closed(monkeypatch, caplog):
    """Scores are now schema-constrained, so the failure mode is an absent verdict rather
    than unparseable prose. It must still fail closed and still leave a trace."""
    monkeypatch.setattr(verifier_service, "generate_json", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING, logger="backend.services.verifier_service"):
        result = verifier_service.score_answer("gia?", "3.6 ty", ["context"])

    assert result.score == 0.0
    assert any(getattr(r, "event", None) == "verifier.judge.empty" for r in caplog.records)


@pytest.mark.parametrize(
    ("raw_score", "expected"),
    [
        (None, 0.0),
        ("0.85", 0.85),
        (85, 0.85),
        (1.5, 1.0),
        (-1, 0.0),
    ],
)
def test_scores_are_coerced_into_range(raw_score, expected):
    """Validation lives on the model now, so every caller gets a score in [0, 1]."""
    result = verifier_service.VerifierResult(faithfulness=raw_score, relevancy=1.0)
    assert result.faithfulness == pytest.approx(expected)


def test_the_weaker_dimension_decides_the_score():
    """Truthful but off-topic must fail exactly like on-topic but invented."""
    assert verifier_service.VerifierResult(faithfulness=1.0, relevancy=0.2).score == pytest.approx(0.2)
    assert verifier_service.VerifierResult(faithfulness=0.2, relevancy=1.0).score == pytest.approx(0.2)


def test_pipeline_crash_is_logged_and_still_returns_the_standard_message(monkeypatch, caplog):
    """The single most valuable log line: without it a crash is entirely invisible."""
    import backend.services.agent_pipeline as pipeline

    class _ExplodingGraph:
        def invoke(self, _state):
            raise _SimulatedError("graph exploded")

    monkeypatch.setattr(pipeline, "_get_graph", lambda: _ExplodingGraph())

    with caplog.at_level(logging.ERROR, logger="backend.services.agent_pipeline"):
        result = run_pipeline("gia can 2PN?", project_id="ocean-park-3")

    assert result.draft_answer == GENERATION_ERROR_MESSAGE
    assert result.verifier_score == 0.0
    assert result.requires_hitl is False

    record = next(r for r in caplog.records if getattr(r, "event", None) == "pipeline.crash")
    assert record.project_id == "ocean-park-3"
    assert record.exc_info is not None


def test_rejected_token_is_logged_without_ever_including_the_token(caplog):
    """A JWT prefix is header+payload and decodes to real data - never log any of it."""
    from backend.core.security import decode_token

    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJzYWxlX3Rlc3QifQ.invalid-signature-part"

    with caplog.at_level(logging.WARNING, logger="backend.core.security"):
        assert decode_token(token) is None

    record = next(r for r in caplog.records if getattr(r, "event", None) == "auth.token.rejected")
    assert record.reason
    assert token not in caplog.text
    assert "eyJhbGciOiJIUzI1NiJ9" not in caplog.text


def test_unparseable_price_is_logged_at_debug_and_left_blank(caplog):
    with caplog.at_level(logging.DEBUG, logger="backend.services.inventory_service"):
        assert _to_float("not-a-number") is None

    assert any(getattr(r, "event", None) == "inventory.price.unparseable" for r in caplog.records)


def test_incomplete_inventory_record_logs_field_names_only(caplog):
    """Unit codes and prices are business data; only the missing field names are safe."""
    with caplog.at_level(logging.WARNING, logger="backend.services.inventory_service"):
        assert _parse_unit({"unit_code": "OP3-A-0203", "price": 3600000000}) is None

    record = next(r for r in caplog.records if getattr(r, "event", None) == "inventory.record.incomplete")
    assert set(record.missing_fields) == {"project_id", "status"}
    assert "OP3-A-0203" not in caplog.text
    assert "3600000000" not in caplog.text


def test_non_dict_inventory_record_is_logged(caplog):
    with caplog.at_level(logging.WARNING, logger="backend.services.inventory_service"):
        assert _parse_unit("just a string") is None

    assert any(getattr(r, "event", None) == "inventory.record.not_dict" for r in caplog.records)
