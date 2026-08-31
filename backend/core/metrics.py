"""Prometheus metric definitions shared by HTTP and dependency probes."""

from prometheus_client import Counter, Gauge, Histogram

HTTP_REQUESTS_TOTAL = Counter(
    "salesmate_http_requests_total",
    "Total HTTP requests handled by the API.",
    ("method", "route", "status"),
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "salesmate_http_request_duration_seconds",
    "HTTP request duration in seconds.",
    ("method", "route"),
    buckets=(0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "salesmate_http_requests_in_progress",
    "HTTP requests currently being processed.",
    ("method",),
)
DEPENDENCY_READY = Gauge(
    "salesmate_dependency_ready",
    "Whether a configured dependency passed its latest readiness probe (1=yes, 0=no).",
    ("dependency",),
)
DEPENDENCY_CHECK_DURATION_SECONDS = Histogram(
    "salesmate_dependency_check_duration_seconds",
    "Dependency readiness-check duration in seconds.",
    ("dependency",),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2, 3, 5),
)
