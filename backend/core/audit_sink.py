"""Persists audit events to MySQL, alongside the stdout log.

Why a table at all: stdout logs are gone when the container is replaced. They
answer "what broke just now"; this answers "who logged in last Tuesday" and
"which Sale confirmed that price" months later.

Two properties this module must never lose, both verified by tests:

1. **It writes on its own session.** Reusing the request's session would mean an
   `auth.login.failure` — written immediately before `raise HTTPException` — is
   discarded when the session closes without a commit, losing exactly the
   security events most worth keeping. Committing on the request's session is
   worse still: it would also commit whatever half-finished business work is
   pending there (e.g. the document row in `documents.upload`, before ingestion
   has run).

2. **It never raises.** A failure to record an audit row must not turn a working
   request into a 500. The stdout line has already been emitted by then, so a
   DB outage degrades the trail rather than erasing it.
"""

import json
import logging

from backend.core.context import get_request_id
from backend.core.mysql_client import SessionLocal
from backend.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

_COLUMN_FIELDS = ("user_id", "username")


def persist_event(event: str, fields: dict) -> None:
    """Write one audit row. Swallows every error by design — see module docstring."""
    if SessionLocal is None:
        return

    session = None
    try:
        session = SessionLocal()
        session.add(
            AuditLog(
                event=event,
                user_id=_as_int(fields.get("user_id")),
                username=_as_str(fields.get("username")),
                request_id=get_request_id(),
                payload=_json_safe({key: value for key, value in fields.items() if key not in _COLUMN_FIELDS}) or None,
            )
        )
        session.commit()
    except Exception:
        logger.warning(
            "Could not persist audit event to MySQL",
            exc_info=True,
            extra={"event": "audit.persist.failed", "failed_event": event},
        )
    finally:
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.warning(
                    "Could not close audit persistence session",
                    exc_info=True,
                    extra={"event": "audit.session.close.failed"},
                )


def _json_safe(fields: dict) -> dict:
    """Coerce values the JSON column cannot store.

    A single unserialisable value would abort the whole INSERT and lose the
    event, so anything json cannot handle is stringified rather than dropped.
    """
    safe = {}
    for key, value in fields.items():
        try:
            json.dumps(value)
            safe[key] = value
        except Exception:
            try:
                safe[key] = str(value)
            except Exception:
                safe[key] = "<unrepresentable>"
    return safe


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_str(value: object) -> str | None:
    return value[:50] if isinstance(value, str) else None
