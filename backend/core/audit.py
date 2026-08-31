"""Business-event audit trail on a dedicated logger.

Separate from diagnostic logging on purpose. These lines answer *who did what*,
are always INFO, and are pinned to INFO in `logging_config` so that running
production at `LOG_LEVEL=WARNING` cannot silently switch off the trail. Routing
them to their own sink later (a file, a SIEM) means editing one entry in the
dictConfig rather than touching any call site.

Every event carries the `request_id` through the formatter, so an audit line
joins to its access line and to any traceback from the same request.

**What must never appear here**: passwords or hashes, JWTs (not even a prefix),
the HITL confirmed content going to a customer, document file contents, any
inventory field *value*, or a customer's contact details (phone number, full
name). Truncate free text with `truncate()`.

Contact details are singled out because `audit_sink` copies the whole payload
into `audit_logs.payload`, a table deliberately created without a foreign key so
its rows outlive the user they describe — a phone number written here survives
the account being deleted. Log a boolean (`phone_captured=True`) instead: it
answers the only operational question anyone actually has.

Free text bound for the trail goes through `redact_and_truncate()`, which strips
phone numbers, citizen IDs and emails (`backend/utils/pii.py`). Plain
`truncate()` does not redact, because its other callers build inbox previews for
the Sale's own screen, where the customer's number is the point. The redaction is
a backstop, not permission to stop thinking: it does not attempt names, and a
field holding a contact detail on purpose still must not be logged at all.
"""

import logging

from backend.utils.pii import redact_pii

_audit = logging.getLogger("salesmate.audit")

DEFAULT_TRUNCATE_LIMIT = 200

_RESERVED_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {
    "message",
    "asctime",
    "taskName",
}


def _safe_fields(fields: dict) -> dict:
    return {(f"field_{key}" if key in _RESERVED_RECORD_ATTRS else key): value for key, value in fields.items()}


def log_event(event: str, **fields: object) -> None:
    """Emit one audit record to stdout, then persist it to MySQL.

    Never raises — auditing must not break a request.

    Two sinks with different jobs: stdout is immediate and joins to the
    tracebacks of the same request while they are still in the collector's
    window; the table survives the container and answers questions months later.
    stdout goes first so a database outage degrades the trail instead of
    erasing the event.
    """
    try:
        _audit.info(event, extra={"event": event, "audit": True, **_safe_fields(fields)})
    except Exception:  # pragma: no cover - defensive; logging must never propagate
        _audit.warning("Audit event failed to emit", extra={"event": "audit.failed", "failed_event": event})

    from backend.core.audit_sink import persist_event

    persist_event(event, fields)


def truncate(text: str | None, limit: int = DEFAULT_TRUNCATE_LIMIT) -> str | None:
    """Cap free text so one long input cannot dominate the log.

    Does **not** redact: three of its callers build inbox previews for the Sale's own
    screen (`sale_live.py`, `admin_sales.py`), where a customer's number is exactly what
    the Sale needs in order to call them back. Use `redact_and_truncate` for anything
    heading into the audit trail.
    """
    if text is None:
        return None
    return text if len(text) <= limit else text[:limit] + "…"


def redact_and_truncate(text: str | None, limit: int = DEFAULT_TRUNCATE_LIMIT) -> str | None:
    """`truncate`, with contact details stripped first — for text bound for the trail.

    Redact *before* truncating: truncation can cut a phone number in half, and eight digits
    of somebody's number is still their number sitting in a table with no foreign key.

    A backstop for the rule at the top of this module, not a replacement for it. It exists
    because the rule was kept by hand and quietly stopped holding: `customer_chat.py` began
    logging a customer's own words through a flag whose comment still described the text as
    a Sale's. It cannot help a field that carries a contact detail on purpose — that must
    not be logged at all — and it does not attempt names.
    """
    return truncate(redact_pii(text), limit)
