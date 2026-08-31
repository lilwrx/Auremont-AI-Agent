"""The audit trail must survive log-level tuning and never break a request."""

import logging

from backend.core.audit import DEFAULT_TRUNCATE_LIMIT, log_event, truncate
from backend.core.logging_config import AUDIT_LOGGER_NAME


def test_event_reaches_the_audit_logger_with_its_fields(capture_audit):
    log_event("sale.query", session_id=7, verifier_score=0.91)

    record = capture_audit[-1]
    assert record.event == "sale.query"
    assert record.session_id == 7
    assert record.verifier_score == 0.91
    assert record.audit is True


def test_audit_survives_a_raised_root_log_level(capture_audit):
    """LOG_LEVEL=WARNING in production must not silently kill the audit trail."""
    root = logging.getLogger()
    previous = root.level
    root.setLevel(logging.ERROR)
    try:
        log_event("auth.login.success", username="sale_test")
    finally:
        root.setLevel(previous)

    assert capture_audit[-1].event == "auth.login.success"


def test_log_event_never_raises():
    class Exploding:
        def __repr__(self) -> str:
            raise RuntimeError("repr blew up")

    log_event("some.event", payload=Exploding())


def test_truncate_shortens_long_text():
    result = truncate("x" * (DEFAULT_TRUNCATE_LIMIT + 50))

    assert result is not None
    assert len(result) == DEFAULT_TRUNCATE_LIMIT + 1


def test_truncate_leaves_short_text_untouched():
    assert truncate("gia can 2PN?") == "gia can 2PN?"


def test_truncate_passes_none_through():
    assert truncate(None) is None


def test_audit_logger_does_not_propagate_to_root():
    """Prevents audit lines being duplicated by the root handler."""
    assert logging.getLogger(AUDIT_LOGGER_NAME).propagate is False
