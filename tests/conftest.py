import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.config import settings
from backend.core.context import request_id_var
from backend.core.logging_config import AUDIT_LOGGER_NAME
from backend.core.mysql_client import Base
from backend.main import app


@pytest.fixture
def db_session():
    """A fresh in-memory SQLite database, isolated per test.

    Was hand-rolled, byte-for-byte identical, in 28 test files before moving here. A file
    that needs different setup (a pre-seeded row, a custom teardown) still can — a fixture
    of the same name defined in that file shadows this one, which is how e.g. the document
    tests that also need `Base.metadata.drop_all` before the next test's `create_all` keep
    working unchanged.
    """
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = testing_session()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def raw_client():
    """Client that lets the app's own 500 handler run.

    TestClient defaults to `raise_server_exceptions=True`, where
    ServerErrorMiddleware re-raises instead of calling our handler — so the
    response body can never be asserted. Kept separate from `client` on purpose:
    flipping the default globally would turn every unexpected error in the
    existing tests from a clear traceback into a puzzling `assert 200 == 500`.
    """
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def _reset_request_id():
    """Stop a request id set by one test from leaking into the next."""
    token = request_id_var.set("")
    yield
    request_id_var.reset(token)


@pytest.fixture(autouse=True)
def _stub_dependency_readiness(monkeypatch):
    """Unit/API tests do not require live MySQL, Qdrant, and Redis processes."""

    async def healthy_readiness():
        return {
            "status": "ok",
            "checks": {name: {"status": "ok", "latency_ms": 0.0} for name in ("mysql", "qdrant", "redis")},
        }

    monkeypatch.setattr("backend.main.check_readiness", healthy_readiness)


@pytest.fixture(autouse=True)
def _no_live_qdrant(monkeypatch):
    """Refuse a Qdrant connection instantly instead of waiting out its socket timeout.

    CONTRIBUTING says the suite is hermetic, and it was not: `cache_service.clear_cache`
    runs on every conflict resolve and document visibility change, and it builds a real
    client against `qdrant_url`. The call is best-effort and swallows its own failure, so
    nothing ever went red — it just sat there. On a machine that refuses connections to
    localhost:6333 that costs milliseconds; on one whose firewall drops them it costs
    QDRANT_TIMEOUT_SECONDS per call, which is the difference between a 2-minute suite and
    an 8-hour one. Raising at construction keeps every caller on the same branch it
    already took (an exception it catches) and makes the cost a constant.

    A test that needs Qdrant to *work* stubs the service function it calls — see
    `vector_syncs` in tests/test_api/test_admin_conflicts.py — and never reaches here.
    """
    from backend.core import qdrant_client as qdrant_module

    def _refuse(*args, **kwargs):
        raise ConnectionError("No live Qdrant in tests; stub the service function you need.")

    monkeypatch.setattr(qdrant_module, "QdrantClient", _refuse)
    qdrant_module.get_qdrant_client.cache_clear()
    yield
    qdrant_module.get_qdrant_client.cache_clear()


@pytest.fixture(autouse=True)
def _no_live_cohere(monkeypatch):
    """Prevent tests from making billed API calls."""

    monkeypatch.setattr(settings, "cohere_api_key", "")


@pytest.fixture(autouse=True)
def _no_live_redis(monkeypatch):
    """Same rule for long-term memory: an empty URL is how the feature is switched off.

    `get_redis_client` returns None on an empty `redis_url`, which memory_service already
    handles as "no profile yet". The default is `redis://localhost:6379/0`, so without
    this every memory read paid two socket timeouts to discover nothing was listening.
    """
    from backend.core import redis_client as redis_module

    monkeypatch.setattr(settings, "redis_url", "")
    redis_module.get_redis_client.cache_clear()
    yield
    redis_module.get_redis_client.cache_clear()


@pytest.fixture(autouse=True)
def _reset_anonymous_rate_limit():
    """Clear throttle budget between tests."""
    from backend.core import rate_limit

    rate_limit._hits.clear()
    yield
    rate_limit._hits.clear()


@pytest.fixture(autouse=True)
def _no_live_audit_sink(monkeypatch):
    """Keep the audit trail on stdout in tests instead of reaching for MySQL.

    `persist_event` runs on every audited action — login, sale query, HITL confirm — and
    opens its own session against `DATABASE_URL`. It swallows the failure by design, so a
    developer with a MySQL URL in `.env` but no server running saw only a `WARNING` line
    while each request quietly paid a connection timeout per audit event. That was most of
    the wall-clock time in tests/test_api.

    `None` is the module's own documented "no database configured" path (see
    tests/test_core/test_audit_sink.py), not a stub — and the tests that assert on audit
    content read the stdout record through `capture_audit`, which is unaffected. The two
    files that exercise the MySQL write substitute their own factory, which wins over this.
    """
    from backend.core import audit_sink

    monkeypatch.setattr(audit_sink, "SessionLocal", None)


@pytest.fixture(autouse=True)
def _disable_live_semantic_conflict_calls(monkeypatch):
    """Unit tests opt in explicitly; no test may accidentally spend an LLM request."""

    monkeypatch.setattr(settings, "semantic_conflict_detection_enabled", False)


@pytest.fixture(autouse=True)
def _disable_live_observability_writes(monkeypatch):
    """Tests opt in explicitly; never write test metrics to a developer's MySQL."""

    monkeypatch.setattr(settings, "observability_metrics_enabled", False)


@pytest.fixture(autouse=True)
def _disable_live_lead_enrichment(monkeypatch):
    """Same rule as the semantic-conflict guard: no test spends an LLM request by accident.

    Lead scoring runs on every customer turn, so without this any test that posts a customer
    message and happens to land inside the enrichment decision band reaches for Gemini and
    hangs on the network. Rule scoring — the part these tests care about — is unaffected.
    """

    monkeypatch.setattr(settings, "lead_scoring_llm_enabled", False)


@pytest.fixture
def capture_audit():
    """Collect records from the audit logger.

    `caplog` cannot see these: it attaches to the root logger and relies on
    propagation, while the audit logger sets `propagate = False` by design.
    Attaching a handler directly is immune to that and yields the real
    LogRecords, so tests can assert on `record.__dict__` fields.
    """
    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Collector()
    logger = logging.getLogger(AUDIT_LOGGER_NAME)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
