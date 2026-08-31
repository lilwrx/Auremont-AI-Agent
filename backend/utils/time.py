from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current UTC time as a naive datetime — a replacement for deprecated `datetime.utcnow()`.

    Every timestamp column in `backend/models/` is declared as `DateTime` without a
    timezone, so this must return a naive value: assigning an aware datetime to a naive
    column makes MySQL silently drop the tzinfo, and comparing naive against aware in
    Python raises TypeError. Dropping tzinfo here keeps one single convention across
    the whole system: naive means UTC.
    """
    return datetime.now(UTC).replace(tzinfo=None)
