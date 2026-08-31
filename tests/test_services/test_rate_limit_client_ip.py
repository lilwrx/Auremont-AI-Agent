"""Which address the anonymous throttle counts against.

Two failure modes sit on opposite sides of this one function: read X-Forwarded-For and a
visitor forges a fresh IP per request, bypassing the limit; ignore it behind a proxy and
every visitor shares the proxy's bucket, so one busy visitor locks everyone out. The
trusted-hop count is what separates them.
"""

import pytest

from backend.core import rate_limit
from backend.core.config import settings


class _FakeClient:
    def __init__(self, host: str):
        self.host = host


class _FakeRequest:
    def __init__(self, peer: str | None, forwarded: str | None = None):
        self.client = _FakeClient(peer) if peer else None
        self.headers = {"x-forwarded-for": forwarded} if forwarded else {}


@pytest.fixture
def proxies(monkeypatch):
    def _set(count: int):
        monkeypatch.setattr(settings, "trusted_proxy_count", count)

    return _set


class TestNoProxyConfigured:
    def test_the_socket_peer_is_used(self, proxies):
        proxies(0)
        assert rate_limit._client_ip(_FakeRequest("203.0.113.9")) == "203.0.113.9"

    def test_a_spoofed_header_is_ignored(self, proxies):
        """The default deployment has no proxy, so this header is pure client input —
        honouring it would hand every visitor an unlimited supply of fresh buckets."""
        proxies(0)
        request = _FakeRequest("203.0.113.9", forwarded="1.2.3.4")

        assert rate_limit._client_ip(request) == "203.0.113.9"

    def test_a_missing_client_is_not_an_error(self, proxies):
        proxies(0)
        assert rate_limit._client_ip(_FakeRequest(None)) == "unknown"


class TestBehindOneProxy:
    def test_the_visitor_address_is_read_from_the_header(self, proxies):
        proxies(1)
        request = _FakeRequest("10.0.0.1", forwarded="203.0.113.9")

        assert rate_limit._client_ip(request) == "203.0.113.9"

    def test_client_supplied_entries_further_left_are_ignored(self, proxies):
        """A visitor prepending their own hops must not push the real address out of view."""
        proxies(1)
        request = _FakeRequest("10.0.0.1", forwarded="1.1.1.1, 2.2.2.2, 203.0.113.9")

        assert rate_limit._client_ip(request) == "203.0.113.9"

    def test_a_missing_header_falls_back_to_the_peer(self, proxies):
        proxies(1)
        assert rate_limit._client_ip(_FakeRequest("10.0.0.1")) == "10.0.0.1"


class TestBehindTwoProxies:
    def test_the_hop_count_decides_how_far_right_to_read(self, proxies):
        proxies(2)
        request = _FakeRequest("10.0.0.1", forwarded="203.0.113.9, 10.0.0.5")

        assert rate_limit._client_ip(request) == "203.0.113.9"

    def test_a_chain_shorter_than_configured_does_not_read_past_the_start(self, proxies):
        proxies(3)
        request = _FakeRequest("10.0.0.1", forwarded="203.0.113.9")

        assert rate_limit._client_ip(request) == "203.0.113.9"
