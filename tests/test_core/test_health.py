import pytest

from backend.core import health


@pytest.mark.asyncio
async def test_readiness_checks_all_required_dependencies(monkeypatch):
    calls: list[str] = []

    monkeypatch.setattr(health, "_check_mysql", lambda: calls.append("mysql"))
    monkeypatch.setattr(health, "_check_qdrant", lambda: calls.append("qdrant"))
    monkeypatch.setattr(health, "_check_redis", lambda: calls.append("redis"))

    result = await health.check_readiness()

    assert result["status"] == "ok"
    assert set(calls) == {"mysql", "qdrant", "redis"}


@pytest.mark.asyncio
async def test_readiness_reports_dependency_failure_without_leaking_message(monkeypatch):
    def fail_qdrant() -> None:
        raise ConnectionError("secret host details")

    monkeypatch.setattr(health, "_check_mysql", lambda: None)
    monkeypatch.setattr(health, "_check_qdrant", fail_qdrant)
    monkeypatch.setattr(health, "_check_redis", lambda: None)

    result = await health.check_readiness()

    assert result["status"] == "unavailable"
    assert result["checks"]["qdrant"]["reason"] == "ConnectionError"
    assert "secret host details" not in str(result)
