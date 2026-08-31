# Changelog

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and releases follow Semantic Versioning.

## [Unreleased]

### Added

- Dependency-aware readiness probes for MySQL, Qdrant, and Redis at `/health/ready`, plus a process-only liveness
  probe at `/health/live`.
- Prometheus metrics at `/metrics`, including HTTP request, latency, in-progress, dependency state, and dependency
  probe latency series.
- Measurable 30-day availability, latency, and error-rate objectives in `SLO.md`.
- Contributor community standards in `CODE_OF_CONDUCT.md`.

### Changed

- `/health` is now a backward-compatible readiness endpoint and returns HTTP 503 when a required dependency fails.
- Docker Compose, the image healthcheck, and Render now use `/health/ready`.
- Ruff now enforces Bugbear, Bandit, Simplify, and return-style rules in addition to the existing rule groups.

### Fixed

- Bound fact-extraction state explicitly instead of capturing a loop variable in an ingestion closure (`B023`).
