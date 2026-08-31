"""The log format is an interface: dashboards and greps depend on its shape."""

import json
import logging

import pytest

from backend.core.context import request_id_var
from backend.core.logging_config import ConsoleFormatter, JsonFormatter, RedactingFilter, setup_logging


def _record(**kwargs) -> logging.LogRecord:
    record = logging.LogRecord(
        name=kwargs.pop("name", "test.logger"),
        level=kwargs.pop("level", logging.INFO),
        pathname="test.py",
        lineno=42,
        msg=kwargs.pop("msg", "hello"),
        args=kwargs.pop("args", ()),
        exc_info=kwargs.pop("exc_info", None),
    )
    for key, value in kwargs.items():
        setattr(record, key, value)
    return record


def test_json_output_is_parseable_with_core_fields():
    payload = json.loads(JsonFormatter().format(_record()))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.logger"
    assert payload["message"] == "hello"
    assert payload["line"] == 42
    assert "timestamp" in payload


def test_extra_fields_are_promoted_to_top_level():
    """Nested extras would defeat `jq 'select(.event=="pipeline.crash")'`."""
    payload = json.loads(JsonFormatter().format(_record(event="pipeline.crash", project_id="op3")))

    assert payload["event"] == "pipeline.crash"
    assert payload["project_id"] == "op3"


def test_vietnamese_text_survives_unescaped():
    """ensure_ascii=False: unicode-escaped output makes `docker logs` unreadable."""
    payload = JsonFormatter().format(_record(msg="Không đủ thông tin, liên hệ Admin"))

    assert "Không đủ thông tin" in payload
    assert json.loads(payload)["message"] == "Không đủ thông tin, liên hệ Admin"


def test_unserialisable_extra_does_not_raise():
    """A logging call must never take down the request that made it."""

    class Opaque:
        def __repr__(self) -> str:
            return "<opaque>"

    payload = json.loads(JsonFormatter().format(_record(obj=Opaque())))

    assert payload["obj"] == "<opaque>"


def test_exception_is_recorded_with_type_and_traceback():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        payload = json.loads(JsonFormatter().format(_record(exc_info=sys.exc_info())))

    assert payload["exc_type"] == "ValueError"
    assert "Traceback" in payload["exception"]
    assert "boom" in payload["exception"]


def test_request_id_is_read_from_contextvar():
    token = request_id_var.set("trace-abc")
    try:
        payload = json.loads(JsonFormatter().format(_record()))
    finally:
        request_id_var.reset(token)

    assert payload["request_id"] == "trace-abc"


def test_request_id_is_empty_outside_a_request():
    assert json.loads(JsonFormatter().format(_record()))["request_id"] == ""


@pytest.mark.parametrize(
    "field",
    ["password", "token", "api_key", "authorization", "secret_key", "aws_access_key", "refresh_token"],
)
def test_redacting_filter_masks_sensitive_keys(field):
    record = _record(**{field: "super-sensitive-value"})

    RedactingFilter().filter(record)

    assert getattr(record, field) == "***REDACTED***"
    assert "super-sensitive-value" not in JsonFormatter().format(record)


def test_redacting_filter_leaves_ordinary_fields_alone():
    record = _record(project_id="ocean-park-3", verifier_score=0.91)

    RedactingFilter().filter(record)

    assert record.project_id == "ocean-park-3"
    assert record.verifier_score == 0.91


def test_console_formatter_shows_request_id_and_extras():
    token = request_id_var.set("abcdef1234567890")
    try:
        line = ConsoleFormatter().format(_record(event="http.access"))
    finally:
        request_id_var.reset(token)

    assert "req=abcdef12" in line
    assert "event=http.access" in line


def test_setup_logging_keeps_existing_loggers_enabled():
    """disable_existing_loggers=True would silence uvicorn's startup tracebacks."""
    existing = logging.getLogger("uvicorn.error")

    setup_logging()

    assert existing.disabled is False
