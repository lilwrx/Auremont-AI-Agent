"""Cache hit vẫn phải qua cổng HITL.

Một cache hit đi thẳng tới END (`_route_after_cache`), nên `_cache_check` là chỗ DUY NHẤT
cổng HITL còn có thể bật cho câu trả lời lấy từ cache. Trước đây `_store_cache` từ chối mọi
câu `requires_hitl`, mà trong kho tài liệu bất động sản thì gần như câu nào cũng chạm giá —
kết quả là collection cache chưa từng được tạo. Đổi lại: cache cả câu chạm giá, nhưng chạy
lại RiskCheck khi lấy ra.
"""

from backend.core.enums import DocumentVisibility
from backend.services import agent_pipeline
from backend.services.cache_service import CachedAnswer

PRICE_ANSWER = "- Căn 2PN The Zurich giá 2,5 tỷ đồng, đã bao gồm VAT."
SAFE_ANSWER = "- Tiện ích nội khu gồm bể bơi bốn mùa và phòng gym."


def _cached(answer: str) -> CachedAnswer:
    return CachedAnswer(answer=answer, citations=[{"document_id": 1, "title": "t"}], verifier_score=0.95)


def _result(**kw):
    base = dict(draft_answer=PRICE_ANSWER, citations=[], verifier_score=0.95, requires_hitl=True)
    base.update(kw)
    return agent_pipeline.PipelineResult(**base)


def test_cached_price_answer_still_raises_hitl(monkeypatch):
    """Điểm mấu chốt: câu chạm giá lấy từ cache vẫn phải bắt Sale xác nhận."""
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **kw: _cached(PRICE_ANSWER))

    result = agent_pipeline._cache_check({"query": "giá 2PN The Zurich?"})

    assert result["used_cache"] is True
    assert result["requires_hitl"] is True


def test_cached_safe_answer_does_not_raise_hitl(monkeypatch):
    """Không phải cứ cache là bật HITL — câu mô tả tiện ích vẫn đi thẳng."""
    monkeypatch.setattr(agent_pipeline.cache_service, "lookup_cache", lambda *a, **kw: _cached(SAFE_ANSWER))

    result = agent_pipeline._cache_check({"query": "tiện ích có gì?"})

    assert result["used_cache"] is True
    assert result["requires_hitl"] is False


def test_hitl_verdict_is_recomputed_not_read_from_the_cache_row(monkeypatch):
    """RiskCheck chạy trên CHÍNH văn bản cache, không tin vào cờ lưu kèm.

    Nếu ai đó ghi nhầm một câu chạm giá vào cache như thể vô hại, cổng vẫn phải bật.
    """
    monkeypatch.setattr(
        agent_pipeline.cache_service,
        "lookup_cache",
        lambda *a, **kw: _cached("- Khách đặt cọc 200 triệu để giữ chỗ."),
    )

    assert agent_pipeline._cache_check({"query": "đặt cọc bao nhiêu?"})["requires_hitl"] is True


def test_price_answer_is_now_cached(monkeypatch):
    """Đây là thứ mở khoá cả tính năng: trước đây câu chạm giá không bao giờ được ghi."""
    stored: dict = {}
    monkeypatch.setattr(agent_pipeline.cache_service, "store_cache", lambda **kw: stored.update(kw))

    agent_pipeline._store_cache("giá 2PN?", _result(), None, DocumentVisibility.INTERNAL)

    assert stored.get("answer") == PRICE_ANSWER


def test_answer_with_listings_is_not_cached(monkeypatch):
    """CachedAnswer không mang được listings — cache lại sẽ mất thẻ căn hộ."""
    stored: dict = {}
    monkeypatch.setattr(agent_pipeline.cache_service, "store_cache", lambda **kw: stored.update(kw))

    agent_pipeline._store_cache(
        "còn căn 2PN nào?",
        _result(listings=[{"project_name": "The Zurich", "price_range": "2,5 tỷ đồng"}]),
        None,
        DocumentVisibility.INTERNAL,
    )

    assert stored == {}


def test_answer_with_images_is_not_cached(monkeypatch):
    stored: dict = {}
    monkeypatch.setattr(agent_pipeline.cache_service, "store_cache", lambda **kw: stored.update(kw))

    agent_pipeline._store_cache(
        "cho xem mặt bằng", _result(images=[{"url": "http://x/a.jpg"}]), None, DocumentVisibility.INTERNAL
    )

    assert stored == {}


def test_low_scoring_answer_is_not_cached(monkeypatch):
    """Cache một câu trả lời tệ chỉ là nhân bản cái tệ đó."""
    stored: dict = {}
    monkeypatch.setattr(agent_pipeline.cache_service, "store_cache", lambda **kw: stored.update(kw))

    agent_pipeline._store_cache("giá 2PN?", _result(verifier_score=0.3), None, DocumentVisibility.INTERNAL)

    assert stored == {}
