# Service Level Objectives

This document defines the production reliability targets for the SalesMate API. Targets use a rolling 30-day
window and are reviewed monthly. They are engineering SLOs, not by themselves a contractual or financial SLA.

## Service boundary

The measured service is the public FastAPI backend and the MySQL, Qdrant, and Redis dependencies required by its
readiness contract. `/health/live` proves only that the API process is responsive. `/health/ready` and its backward-
compatible alias `/health` return HTTP 503 if any required dependency fails its probe.

Scheduled maintenance is included in the SLO unless users have been notified at least 72 hours in advance. Approved
maintenance may consume at most two hours per calendar month and must be reported separately; dependency/provider
outages are not silently excluded.

## Objectives

| User journey | SLI | 30-day objective | Error budget |
| --- | --- | ---: | ---: |
| API availability | Successful external probes to `/health/ready` divided by all scheduled probes | 99.90% | 43m 49s per 30 days |
| Non-AI API latency | p95 duration for HTTP 2xx/3xx responses, excluding health and metrics | <= 500 ms | 5% of eligible requests may exceed 500 ms |
| Interactive chat latency | p95 duration for Sale and Customer chat requests | <= 5 s | 5% of eligible requests may exceed 5 s |
| Semantic-cache latency | p95 duration for chat requests identified as cache hits in pipeline telemetry | <= 500 ms | 5% of cache hits may exceed 500 ms |
| Server error rate | HTTP 5xx responses divided by all non-probe HTTP responses | < 0.50% | 0.50% of requests |

Cancelled client requests and correctly rejected 4xx requests are excluded from the server-error SLI, but are tracked
separately. A timeout at the external probe counts as unavailable even when the application cannot increment its own
counter.

## Measurement

Prometheus scrapes `/metrics` every 15 seconds. An external black-box probe calls `/health/ready` every 30 seconds;
application metrics alone cannot observe a process that is completely unreachable. Route labels use FastAPI templates
(for example `/api/v1/sessions/{session_id}`), never raw URLs, to avoid unbounded label cardinality.

Key series:

- `salesmate_http_requests_total{method,route,status}`
- `salesmate_http_request_duration_seconds_bucket{method,route,le}`
- `salesmate_http_requests_in_progress{method}`
- `salesmate_dependency_ready{dependency}`
- `salesmate_dependency_check_duration_seconds_bucket{dependency,le}`

Example p95 query (apply the dashboard's route filter for the journey being measured):

```promql
histogram_quantile(
  0.95,
  sum by (le, route) (
    rate(salesmate_http_request_duration_seconds_bucket{route!~"/health.*|/metrics"}[5m])
  )
)
```

Example server-error ratio:

```promql
sum(rate(salesmate_http_requests_total{route!~"/health.*|/metrics",status=~"5.."}[30d]))
/
sum(rate(salesmate_http_requests_total{route!~"/health.*|/metrics"}[30d]))
```

## Alerting and error-budget policy

- Page the on-call owner after three consecutive failed readiness probes or when any
  `salesmate_dependency_ready` series remains `0` for two minutes.
- Page on fast burn when the availability error budget burns at 14.4x for both 5 minutes and 1 hour.
- Create a ticket on slow burn at 3x for both 6 hours and 3 days.
- At 50% monthly budget consumption, pause non-essential reliability-risking releases. At 100%, ship only incident,
  security, and reliability fixes until the rolling window recovers.
- Every SLO breach gets an incident timeline and a blameless corrective-action review within five business days.

## SLA posture

Any customer-facing SLA must define support hours, exclusions, remedies, and service credits in a signed agreement.
It must be set below the measured 99.90% availability SLO to leave an operational safety margin; this repository does
not claim a contractual SLA merely because the engineering SLO exists.
