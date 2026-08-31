"""Rerank tut xuong heuristic thi phai de lai dau vet trong trace.

Cohere Trial key chi cho 10 goi/phut, nen duoi tai that duong fallback duoc di lien tuc.
Neu no khong duoc ghi lai, trace cua Admin trong y het mot lan chay binh thuong va khong
cho nao noi rang cross-encoder chua tung chay.
"""

import pytest

from backend.core import tracing
from backend.core.cohere_client import CohereRerankError
from backend.core.config import settings
from backend.services import rag_service


def _hits(*contents: str) -> list[dict]:
    return [
        {"document_id": i, "title": "t", "page": 1, "content": c, "score": 0.9 - i * 0.1}
        for i, c in enumerate(contents)
    ]


def _rerank_steps(run) -> list[dict]:
    return [s for s in run.as_dict()["steps"] if s["name"] == "rerank"]


@pytest.fixture
def traced(monkeypatch):
    """Bat tracing va mo mot run, tra ve chinh run do de test doc lai cac step."""
    monkeypatch.setattr(settings, "tracing_enabled", True)
    return tracing.start_run(query_len=10, project_id=None, clearance="internal")


@pytest.fixture
def cohere_on(monkeypatch):
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "cohere_api_key", "test-key")


def test_successful_cohere_rerank_is_recorded(traced, cohere_on, monkeypatch):
    monkeypatch.setattr(rag_service, "cohere_rerank", lambda q, docs, **kw: [(1, 0.9), (0, 0.2)])

    rag_service._rerank("giá 2PN", _hits("a", "b"))

    step = _rerank_steps(traced)[0]
    assert step["ranker"] == "cohere"
    assert step["candidate_count"] == 2
    assert "degraded" not in step


def test_fallback_is_recorded_as_degraded(traced, cohere_on, monkeypatch):
    """Day la dong quan trong nhat: rate limit khong duoc phep im lang."""

    def _boom(*_a, **_kw):
        raise CohereRerankError("429 rate limited")

    monkeypatch.setattr(rag_service, "cohere_rerank", _boom)

    rag_service._rerank("giá 2PN", _hits("a", "b"))

    step = _rerank_steps(traced)[0]
    assert step["ranker"] == "heuristic"
    assert step["degraded"] is True


def test_rerank_switched_off_is_not_reported_as_degraded(traced, monkeypatch):
    """Tat rerank la lua chon cau hinh, khong phai su co — dung bao dong gia."""
    monkeypatch.setattr(settings, "rerank_enabled", False)

    rag_service._rerank("giá 2PN", _hits("a", "b"))

    step = _rerank_steps(traced)[0]
    assert step["ranker"] == "heuristic"
    assert step["degraded"] is False


def test_answer_still_returned_when_cohere_fails(cohere_on, monkeypatch):
    """Quan sat duoc la mot chuyen; khong duoc lam hong ket qua la chuyen khac."""

    def _boom(*_a, **_kw):
        raise CohereRerankError("429")

    monkeypatch.setattr(rag_service, "cohere_rerank", _boom)

    ranked = rag_service._rerank("căn 3PN", _hits("suat 2PN gia tot", "bang gia 3PN"))

    assert [h["content"] for h in ranked] == ["bang gia 3PN", "suat 2PN gia tot"]
