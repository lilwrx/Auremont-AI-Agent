"""Minimal per-IP throttle for endpoints reachable with no account.

The public customer chat endpoints (anonymous session creation, anonymous ask) are the
only ones in this app an unauthenticated caller can hit repeatedly for free — every other
route sits behind `require_role`, which already caps abuse to whoever holds a valid
internal/customer JWT. Without this, one visitor could script thousands of LLM calls.

In-process sliding window, no new dependency (no `slowapi`/Redis in requirements.txt).
Deliberately scoped: per-process only, resets on restart, not shared across workers.
Acceptable at this app's current single-instance scale; revisit with Redis if it is ever
run with multiple backend workers/processes.
"""

import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from backend.core.config import settings

_hits: dict[str, deque[float]] = defaultdict(deque)


def _client_ip(request: Request) -> str:
    """The address to throttle on, honouring X-Forwarded-For only as far as it is trustworthy.

    Behind a proxy every request's socket peer is the proxy itself, so throttling on it puts
    all visitors in one bucket. But X-Forwarded-For is client-settable: trusting it outright
    lets one visitor forge a new IP per request and bypass the limit completely. So the value
    is only read when `trusted_proxy_count` says how many proxies actually sit in front, and
    then only the hop that many places from the right — the last entry a trusted proxy wrote.
    Anything further left was supplied by the client and is ignored.
    """
    peer = request.client.host if request.client else "unknown"

    hops = settings.trusted_proxy_count
    if hops <= 0:
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer

    chain = [entry.strip() for entry in forwarded.split(",") if entry.strip()]
    if not chain:
        return peer

    return chain[-hops] if len(chain) >= hops else chain[0]


def anonymous_rate_limit(request: Request) -> None:
    """FastAPI dependency: raise 429 once an IP exceeds the configured window/count."""
    now = time.monotonic()
    window = settings.anonymous_rate_limit_window_seconds
    limit = settings.anonymous_rate_limit_per_window

    ip = _client_ip(request)
    hits = _hits[ip]

    while hits and now - hits[0] > window:
        hits.popleft()

    if len(hits) >= limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Quá nhiều yêu cầu, vui lòng thử lại sau ít phút.",
        )

    hits.append(now)
