"""Low-cardinality Prometheus instrumentation for HTTP requests."""

import time

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.core.metrics import HTTP_REQUEST_DURATION_SECONDS, HTTP_REQUESTS_IN_PROGRESS, HTTP_REQUESTS_TOTAL


class PrometheusMiddleware:
    """Measure every HTTP request using the matched route template as the label."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        HTTP_REQUESTS_IN_PROGRESS.labels(method=method).inc()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            HTTP_REQUESTS_IN_PROGRESS.labels(method=method).dec()
            route = scope.get("route")
            route_label = getattr(route, "path", "unmatched")
            duration = time.perf_counter() - started
            HTTP_REQUESTS_TOTAL.labels(method=method, route=route_label, status=str(status_code)).inc()
            HTTP_REQUEST_DURATION_SECONDS.labels(method=method, route=route_label).observe(duration)
