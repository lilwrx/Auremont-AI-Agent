"""Long-term memory verified against a real Redis, not _FakeRedis.

test_memory_service.py proves the module's *logic* (merge order, capping, fail-open)
against an in-memory dict standing in for Redis — it never once calls
redis.Redis.from_url(...), so a wiring mistake in redis_client.py (wrong URL, wrong
kwargs, a serialization the real client rejects) would pass that whole file and only
surface in production. This file closes that gap: it talks to the actual `ai20k_redis`
container from docker-compose.yml, the same one a real Sale's profile is written to.

Skipped automatically when Redis is unreachable (mirrors tests/test_e2e's guard for
MySQL) rather than failing the suite for anyone running `pytest` without Docker up.
"""

import uuid

import pytest
import redis

from backend.core import redis_client as redis_module
from backend.core.config import get_settings
from backend.services import memory_service


def _redis_is_up() -> bool:
    try:
        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=2, socket_timeout=2)
        return bool(client.ping())
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _redis_is_up(),
    reason="Redis not reachable - start it with `docker compose up -d redis`.",
)


@pytest.fixture(autouse=True)
def _no_live_redis(monkeypatch):
    """Override conftest's autouse fixture of the same name.

    conftest.py blanks `redis_url` for every test by default, since most of the suite
    should never make a real Redis call. This file exists specifically to make one, so
    the override is a no-op: `redis_url` stays real and the client cache stays clean,
    the same as if this fixture were never defined. A test-scoped fixture in a module
    shadows the identically-named one from conftest, so no test here sees the blanking.
    """
    redis_module.get_redis_client.cache_clear()
    yield
    redis_module.get_redis_client.cache_clear()


@pytest.fixture
def key():
    """A unique key per test, deleted on both sides so runs never accumulate real keys."""
    k = f"memory:test:{uuid.uuid4().hex[:12]}"
    yield k
    memory_service.forget(k)


def test_remember_then_load_round_trips_through_real_redis(key):
    memory_service.remember(key, "Can 2PN gia 3.6 ty duoc khong?")

    profile = memory_service.load_profile(key)

    assert profile.unit_types == ["2PN"]
    assert profile.budgets == ["3.6 ty"]


def test_a_second_write_merges_with_the_first_newest_first(key):
    memory_service.remember(key, "Can 2PN gia bao nhieu?")
    memory_service.remember(key, "Con can 3PN thi sao?")

    profile = memory_service.load_profile(key)

    assert profile.unit_types == ["3PN", "2PN"]


def test_ttl_is_set_on_the_real_key(key):
    """The 90-day expiry (settings.memory_ttl_seconds) must actually reach Redis, not
    just live in the payload we send — a wrong kwarg to client.set would write the key
    with no expiry and it would never age out."""
    memory_service.remember(key, "Can 2PN gia 3.6 ty duoc khong?")

    client = memory_service.get_redis_client()
    ttl = client.ttl(key)

    assert 0 < ttl <= get_settings().memory_ttl_seconds


def test_forget_deletes_the_real_key(key):
    memory_service.remember(key, "Can 2PN gia 3.6 ty duoc khong?")
    assert not memory_service.load_profile(key).is_empty()

    memory_service.forget(key)

    assert memory_service.load_profile(key).is_empty()


def test_sale_and_customer_profiles_stay_on_separate_real_keys():
    same_id = 4242
    sale_k = memory_service.sale_key(same_id)
    customer_k = memory_service.customer_key(same_id)
    try:
        memory_service.remember(sale_k, "Can 2PN gia 3.6 ty duoc khong?")

        assert not memory_service.load_profile(sale_k).is_empty()
        assert memory_service.load_profile(customer_k).is_empty()
    finally:
        memory_service.forget(sale_k)
        memory_service.forget(customer_k)
