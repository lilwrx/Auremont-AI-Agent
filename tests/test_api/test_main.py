def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert set(data["checks"]) == {"mysql", "qdrant", "redis"}


def test_readiness_returns_503_when_a_dependency_fails(client, monkeypatch):
    async def unavailable_readiness():
        return {
            "status": "unavailable",
            "checks": {
                "mysql": {"status": "ok", "latency_ms": 1.0},
                "qdrant": {"status": "error", "latency_ms": 2.0, "reason": "ConnectionError"},
                "redis": {"status": "ok", "latency_ms": 1.0},
            },
        }

    monkeypatch.setattr("backend.main.check_readiness", unavailable_readiness)

    response = client.get("/health/ready")

    assert response.status_code == 503
    assert response.json()["checks"]["qdrant"]["status"] == "error"


def test_liveness_does_not_depend_on_readiness(client, monkeypatch):
    async def broken_readiness():
        raise AssertionError("liveness must not call dependency checks")

    monkeypatch.setattr("backend.main.check_readiness", broken_readiness)

    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_prometheus_metrics_are_exposed(client):
    client.get("/health/live")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "salesmate_http_requests_total" in response.text
    assert 'route="/health/live"' in response.text
