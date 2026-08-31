"""Liveness and dependency-aware readiness probes."""

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

from sqlalchemy import text

from backend.core.config import get_settings
from backend.core.metrics import DEPENDENCY_CHECK_DURATION_SECONDS, DEPENDENCY_READY
from backend.core.mysql_client import engine
from backend.core.qdrant_client import get_qdrant_client
from backend.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)


def _check_mysql() -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))


def _check_qdrant() -> None:
    get_qdrant_client().get_collections()


def _check_redis() -> None:
    client = get_redis_client()
    if client is None:
        raise RuntimeError("Redis is not configured")
    if not client.ping():
        raise RuntimeError("Redis PING returned a false value")


async def _run_check(name: str, check: Callable[[], None], timeout_seconds: float) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        await asyncio.wait_for(asyncio.to_thread(check), timeout=timeout_seconds)
    except Exception as exc:
        duration = time.perf_counter() - started
        DEPENDENCY_READY.labels(dependency=name).set(0)
        DEPENDENCY_CHECK_DURATION_SECONDS.labels(dependency=name).observe(duration)
        logger.warning(
            "Readiness check failed for %s (%s)",
            name,
            type(exc).__name__,
            extra={
                "event": "health.dependency.failed",
                "dependency": name,
                "error_type": type(exc).__name__,
            },
        )
        return {"status": "error", "latency_ms": round(duration * 1000, 2), "reason": type(exc).__name__}

    duration = time.perf_counter() - started
    DEPENDENCY_READY.labels(dependency=name).set(1)
    DEPENDENCY_CHECK_DURATION_SECONDS.labels(dependency=name).observe(duration)
    return {"status": "ok", "latency_ms": round(duration * 1000, 2)}


async def check_readiness() -> dict[str, Any]:
    """Check every dependency required by the deployed service."""
    settings = get_settings()
    checks = {
        "mysql": _check_mysql,
        "qdrant": _check_qdrant,
        "redis": _check_redis,
    }
    results = await asyncio.gather(
        *(_run_check(name, check, settings.health_check_timeout_seconds) for name, check in checks.items())
    )
    components = dict(zip(checks, results, strict=True))
    ready = all(result["status"] == "ok" for result in results)
    return {"status": "ok" if ready else "unavailable", "checks": components}
