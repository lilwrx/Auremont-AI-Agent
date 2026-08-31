"""Application logging: structured JSON for production, readable text for dev.

Every record carries the `request_id` of the request that produced it, so the
lines belonging to one Sale question can be pulled out of a busy log with a
single grep — including the ones written deep inside the agent pipeline, which
has no access to the request object.

Two rules this module exists to enforce:

* **stdout, never stderr.** Most log collectors classify anything on stderr as
  an error regardless of the `level` field, which would make every INFO line
  look like an incident.
* **Secrets never reach a handler.** `RedactingFilter` masks well-known
  sensitive keys before formatting, so a careless `extra={"token": ...}` at some
  call site cannot leak a credential into the log stream.
"""

import json
import logging
import logging.config
import sys
from datetime import UTC, datetime
from typing import Any

from backend.core.context import get_request_id

_STANDARD_RECORD_FIELDS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)

_SENSITIVE_KEY_PARTS = (
    "password",
    "token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "access_key",
)

_REDACTED = "***REDACTED***"

_NOISY_LIBRARIES = (
    "httpx",
    "httpcore",
    "qdrant_client",
    "urllib3",
    "sqlalchemy.engine",
    "google_genai",
    "python_multipart",
)

AUDIT_LOGGER_NAME = "salesmate.audit"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


class RedactingFilter(logging.Filter):
    """Mask sensitive values in `extra` fields before they reach a formatter."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in record.__dict__:
            if key not in _STANDARD_RECORD_FIELDS and _is_sensitive(key):
                record.__dict__[key] = _REDACTED
        return True


class JsonFormatter(logging.Formatter):
    """One log record per line of JSON."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "func": record.funcName,
            "line": record.lineno,
            "request_id": getattr(record, "request_id", "") or get_request_id(),
        }

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_FIELDS and key != "request_id":
                payload[key] = value

        if record.exc_info:
            payload["exc_type"] = record.exc_info[0].__name__ if record.exc_info[0] else None
            payload["exception"] = self.formatException(record.exc_info)

        if record.stack_info:
            payload["stack"] = self.formatStack(record.stack_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable single line for local development."""

    def format(self, record: logging.LogRecord) -> str:
        request_id = getattr(record, "request_id", "") or get_request_id()
        prefix = f"[req={request_id[:8]}] " if request_id else ""

        extras = " ".join(
            f"{key}={value}"
            for key, value in record.__dict__.items()
            if key not in _STANDARD_RECORD_FIELDS and key != "request_id"
        )

        timestamp = datetime.fromtimestamp(record.created, UTC).strftime("%H:%M:%S")
        line = f"{timestamp} {record.levelname:<8} {prefix}{record.name}: {record.getMessage()}"
        if extras:
            line = f"{line} | {extras}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line


def setup_logging() -> None:
    """Install handlers, formatters and levels for the whole process.

    Called at import time in `backend.main`, deliberately: uvicorn applies its
    own `dictConfig` *before* importing the app module, so configuring here is
    what makes ours win. Doing it in `lifespan` would also miss the test suite,
    which imports the app without entering lifespan.
    """
    from backend.core.config import get_settings

    settings = get_settings()
    formatter = "json" if settings.log_json else "console"
    level = settings.log_level.upper()

    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"redact": {"()": RedactingFilter}},
            "formatters": {
                "json": {"()": JsonFormatter},
                "console": {"()": ConsoleFormatter},
            },
            "handlers": {
                "default": {
                    "class": "logging.StreamHandler",
                    "formatter": formatter,
                    "filters": ["redact"],
                    "stream": sys.stdout,
                }
            },
            "root": {"handlers": ["default"], "level": level},
            "loggers": {
                "uvicorn.access": {"handlers": [], "level": "CRITICAL", "propagate": False},
                "uvicorn.error": {"level": level, "propagate": True, "handlers": []},
                AUDIT_LOGGER_NAME: {
                    "handlers": ["default"],
                    "level": "INFO",
                    "propagate": False,
                },
                **{name: {"level": "WARNING"} for name in _NOISY_LIBRARIES},
            },
        }
    )
