"""Request-id propagation and the structured access log.

Written as pure ASGI rather than `BaseHTTPMiddleware` on purpose:
`BaseHTTPMiddleware` runs the downstream app in a separate anyio task, so a
`ContextVar` set here would not be visible inside the endpoint. Pure ASGI sets
it in the very task that goes on to run the route handler.
"""

import logging
import time
import uuid

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.core.context import reset_request_id, set_request_id

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "x-request-id"

_QUIET_PATHS = frozenset({"/health", "/health/live", "/health/ready", "/metrics"})


def _access_log_level(path: str, status_code: int) -> int:
    if path in _QUIET_PATHS:
        return logging.DEBUG
    if status_code >= 500:
        return logging.ERROR
    if status_code >= 400:
        return logging.WARNING
    return logging.INFO


class RequestContextMiddleware:
    """Assign each request an id, echo it back, and log one line when it ends."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])}
        request_id = headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex

        scope.setdefault("state", {})["request_id"] = request_id

        token = set_request_id(request_id)
        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
                message.setdefault("headers", []).append(
                    (REQUEST_ID_HEADER.encode("latin-1"), request_id.encode("latin-1"))
                )
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            path = scope.get("path", "")
            client = scope.get("client")

            logger.log(
                _access_log_level(path, status_code),
                "%s %s -> %s",
                scope.get("method", ""),
                path,
                status_code,
                extra={
                    "event": "http.access",
                    "method": scope.get("method", ""),
                    "path": path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "client_ip": client[0] if client else None,
                    "user_agent": headers.get("user-agent"),
                },
            )
            reset_request_id(token)
