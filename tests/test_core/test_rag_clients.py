from types import SimpleNamespace

from backend.core import cohere_client, qdrant_client
from backend.core.config import settings


def test_qdrant_client_has_an_interactive_path_timeout(monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    qdrant_client.get_qdrant_client.cache_clear()
    monkeypatch.setattr(qdrant_client, "QdrantClient", fake_client)
    monkeypatch.setattr(
        qdrant_client,
        "get_settings",
        lambda: SimpleNamespace(qdrant_url="http://qdrant", qdrant_api_key="", qdrant_timeout_seconds=7),
    )
    try:
        qdrant_client.get_qdrant_client()
    finally:
        qdrant_client.get_qdrant_client.cache_clear()

    assert captured["timeout"] == 7


def test_cohere_reranker_fails_fast_without_sdk_retries(monkeypatch):
    captured = {}

    def fake_client(**kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(cohere_client, "_client", None)
    monkeypatch.setattr(cohere_client.cohere, "ClientV2", fake_client)
    monkeypatch.setattr(settings, "cohere_rerank_timeout_seconds", 1.75)

    cohere_client.get_cohere_client()

    assert captured["timeout"] == 1.75
    assert captured["max_retries"] == 0
