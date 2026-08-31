from types import SimpleNamespace

import pytest
from qdrant_client import models

from backend.core.cohere_client import CohereRerankError
from backend.core.config import settings
from backend.core.enums import DocumentVisibility
from backend.core.gemini_client import GeminiEmbeddingError
from backend.core.sparse_embedding import embed_documents_sparse
from backend.services import rag_service


class FakeQdrantClient:
    """Ghi lại tham số truy vấn để test soi được filter, limit, collection."""

    def __init__(self, *, points=None, collection_exists: bool = True):
        self.points = points or []
        self.exists = collection_exists
        self.query_calls = []

    def collection_exists(self, collection_name: str) -> bool:
        return self.exists

    def query_points(self, **kwargs):
        self.query_calls.append(kwargs)
        return SimpleNamespace(points=self.points)


def _point(content: str, *, score: float, document_id: int = 1, title: str = "bang-gia.pdf", page: int | None = 1):
    return SimpleNamespace(
        score=score,
        payload={
            "document_id": document_id,
            "title": title,
            "page": page,
            "content": content,
            "visibility": "internal",
        },
    )


@pytest.fixture
def qdrant(monkeypatch):
    """Dense-only retrieval: hybrid off, which is also the production default."""
    fake_client = FakeQdrantClient()
    monkeypatch.setattr(rag_service, "get_qdrant_client", lambda: fake_client)
    monkeypatch.setattr(rag_service, "embed_query", lambda query: [0.1, 0.2, 0.3])
    monkeypatch.setattr(settings, "qdrant_collection", "test_documents")
    monkeypatch.setattr(settings, "hybrid_search_enabled", False)
    monkeypatch.setattr(settings, "rerank_enabled", False)
    return fake_client


@pytest.fixture
def hybrid_qdrant(qdrant, monkeypatch):
    monkeypatch.setattr(settings, "hybrid_search_enabled", True)
    monkeypatch.setattr(
        rag_service,
        "embed_query_sparse",
        lambda query: models.SparseVector(indices=[7, 9], values=[1.0, 1.0]),
    )
    return qdrant


def _conditions(call) -> list:
    return call["query_filter"].must


def _visibility_values(call) -> list[str]:
    for condition in _conditions(call):
        if condition.key == "visibility":
            return list(condition.match.any)
    raise AssertionError("Không có filter visibility")


def _is_current(call) -> bool:
    for condition in _conditions(call):
        if condition.key == "is_current":
            return condition.match.value
    raise AssertionError("Không có filter is_current")


def test_internal_clearance_sees_internal_and_public(qdrant):
    """Sale/Admin đọc được cả hai loại — khớp chính xác sẽ chặn nhầm tài liệu PUBLIC."""
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    assert sorted(_visibility_values(qdrant.query_calls[0])) == ["internal", "public"]


def test_public_clearance_sees_only_public(qdrant):
    rag_service.retrieve("giá căn hộ", DocumentVisibility.PUBLIC)

    assert _visibility_values(qdrant.query_calls[0]) == ["public"]


def test_accepts_plain_string_visibility(qdrant):
    """DocumentVisibility là StrEnum nên caller truyền chuỗi thô vẫn phải đúng."""
    rag_service.retrieve("giá căn hộ", "public")

    assert _visibility_values(qdrant.query_calls[0]) == ["public"]


def test_project_id_scopes_to_project_or_global_documents(qdrant):
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL, project_id="ocean-park-3")

    query_filter = qdrant.query_calls[0]["query_filter"]
    assert any(
        isinstance(condition, models.FieldCondition)
        and condition.key == "project_id"
        and condition.match.value == "ocean-park-3"
        for condition in query_filter.should
    )
    assert any(isinstance(condition, models.IsNullCondition) for condition in query_filter.should)


def test_project_id_omitted_when_not_given(qdrant):
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    keys = [condition.key for condition in _conditions(qdrant.query_calls[0])]
    assert keys == ["visibility", "review_status", "is_current"]


def test_parent_scope_can_include_child_project_documents(qdrant):
    rag_service.retrieve(
        "can 2PN trong cac phan khu",
        DocumentVisibility.INTERNAL,
        project_id="parent-project",
        project_ids=["parent-project", "child-a", "child-b"],
    )

    query_filter = qdrant.query_calls[0]["query_filter"]
    condition = next(
        item for item in query_filter.should if isinstance(item, models.FieldCondition) and item.key == "project_id"
    )
    assert list(condition.match.any) == ["parent-project", "child-a", "child-b"]


def test_excluded_project_is_removed_without_hiding_global_documents(qdrant):
    rag_service.retrieve(
        "ngoài Zenpark còn căn nào",
        DocumentVisibility.INTERNAL,
        excluded_project_ids=["the-zenpark"],
    )

    query_filter = qdrant.query_calls[0]["query_filter"]
    condition = next(
        item for item in query_filter.must_not if isinstance(item, models.FieldCondition) and item.key == "project_id"
    )
    assert list(condition.match.any) == ["the-zenpark"]


def test_retrieval_requires_admin_or_policy_approval(qdrant):
    """A weak LLM suggestion cannot answer before an Admin approves it."""
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    review_condition = next(
        condition for condition in _conditions(qdrant.query_calls[0]) if condition.key == "review_status"
    )
    assert review_condition.match.value == "approved"


def test_retrieval_still_excludes_documents_that_are_not_current(qdrant):
    """The one condition that carries all of it: ingestion clears `is_current` for a
    duplicate, for a document flagged as conflicting, and for an expired/repealed one. If
    this filter ever goes, those three start answering again."""
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    assert _is_current(qdrant.query_calls[0]) is True


def test_retrieval_excludes_unclassified_other_documents(qdrant):
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    excluded = qdrant.query_calls[0]["query_filter"].must_not
    assert len(excluded) == 1
    assert excluded[0].key == "category"
    assert excluded[0].match.value == "other"


def test_overfetches_before_reranking(qdrant):
    """Phải lấy dư rồi mới cắt, nếu không re-rank chỉ xáo lại đúng tập đã bị cắt."""
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL, top_k=5)

    call = qdrant.query_calls[0]
    assert call["limit"] == 5 * rag_service.OVERFETCH_FACTOR
    assert call["collection_name"] == "test_documents"
    assert call["with_payload"] is True
    assert call["query"] == [0.1, 0.2, 0.3]


def test_returns_expected_shape_and_normalized_score(qdrant, monkeypatch):
    """Cosine [-1, 1] của Qdrant được đưa về [0, 1]."""
    monkeypatch.setattr(settings, "rerank_enabled", False)
    qdrant.points = [_point("Giá căn hộ tham khảo.", score=1.0, document_id=7, title="bang-gia.pdf", page=3)]

    result = rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    assert result == [
        {
            "document_id": 7,
            "title": "bang-gia.pdf",
            "content": "Giá căn hộ tham khảo.",
            "page": 3,
            "y_position": None,
            "project_id": None,
            "score": 1.0,
        }
    ]


def test_truncates_to_top_k(qdrant):
    qdrant.points = [_point(f"noi dung {i}", score=0.9) for i in range(12)]

    assert len(rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL, top_k=3)) == 3


def test_skips_points_without_content(qdrant):
    qdrant.points = [
        _point("có nội dung", score=0.9),
        SimpleNamespace(score=0.9, payload={"document_id": 2, "title": "x.pdf", "content": ""}),
        SimpleNamespace(score=0.9, payload=None),
    ]

    result = rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    assert len(result) == 1


def test_identifier_match_outranks_higher_vector_score(qdrant):
    """'2PN' và '3PN' gần như trùng vector; từ khoá là thứ duy nhất tách được hai loại căn."""
    qdrant.points = [
        _point("Căn 3PN diện tích lớn, giá 5.2 tỷ.", score=0.90, document_id=1),
        _point("Căn 2PN giá 3.6 tỷ.", score=0.86, document_id=2),
    ]

    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert result[0]["document_id"] == 2


def test_pure_vector_order_when_query_has_no_identifier(qdrant):
    """Câu hỏi không có mã nào thì không bịa ra tín hiệu từ khoá."""
    qdrant.points = [
        _point("Chính sách thanh toán.", score=0.60, document_id=1),
        _point("Tiện ích nội khu.", score=0.90, document_id=2),
    ]

    result = rag_service.retrieve("tiện ích thế nào", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [2, 1]


def test_exact_identifier_is_a_final_safety_layer_over_fuzzy_scores(qdrant):
    """A large semantic-score gap must not make 3PN answer a question about 2PN."""
    qdrant.points = [
        _point("Căn 3PN diện tích lớn.", score=0.99, document_id=1),
        _point("Căn 2PN diện tích 68 m2.", score=0.40, document_id=2),
    ]

    result = rag_service.retrieve("Thông tin căn 2PN", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [2, 1]


def test_compound_unit_types_are_not_collapsed_into_their_base_type(qdrant):
    qdrant.points = [
        _point("Căn 2PN+1 diện tích 75 m2.", score=0.99, document_id=1),
        _point("Căn 2PN diện tích 68 m2.", score=0.40, document_id=2),
    ]

    result = rag_service.retrieve("Thông tin căn 2PN", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [2, 1]


@pytest.mark.parametrize(
    ("query_label", "document_label"),
    [("2PN", "2BR"), ("2PN+1", "2BR+"), ("3PN", "3BR")],
)
def test_vietnamese_and_english_bedroom_labels_are_equivalent(qdrant, query_label, document_label):
    qdrant.points = [
        _point("Thông tin tổng quan không có loại căn.", score=0.99, document_id=1),
        _point(f"Bảng giá căn {document_label}.", score=0.40, document_id=2),
    ]

    result = rag_service.retrieve(f"Giá căn {query_label}", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [2, 1]


def test_focus_query_keeps_old_identifier_out_of_current_turn_constraints(qdrant):
    """History helps embedding, but the current 3PN turn alone decides exact matching."""
    qdrant.points = [
        _point("Căn 2PN diện tích 68 m2.", score=0.99, document_id=1),
        _point("Căn 3PN diện tích 92 m2.", score=0.40, document_id=2),
    ]

    result = rag_service.retrieve(
        "Trước đó hỏi 2PN. Còn 3PN thì sao?",
        DocumentVisibility.INTERNAL,
        focus_query="Còn 3PN thì sao?",
    )

    assert [hit["document_id"] for hit in result] == [2, 1]


def test_near_duplicate_chunks_from_one_document_are_removed_and_backfilled(qdrant):
    repeated = "Chính sách thanh toán sớm áp dụng chiết khấu năm phần trăm cho khách hàng trong tháng này."
    qdrant.points = [
        _point(repeated, score=0.99, document_id=1),
        _point(repeated, score=0.98, document_id=1),
        _point("Tiến độ thanh toán gồm sáu đợt theo hợp đồng mua bán.", score=0.80, document_id=2),
    ]

    result = rag_service.retrieve("chính sách thanh toán", DocumentVisibility.INTERNAL, top_k=3)

    assert [hit["document_id"] for hit in result] == [1, 2]


def test_identical_content_from_different_documents_is_preserved(qdrant):
    repeated = "Điều khoản này xuất hiện trong hai tài liệu độc lập cần đối chiếu nguồn."
    qdrant.points = [
        _point(repeated, score=0.99, document_id=1),
        _point(repeated, score=0.98, document_id=2),
    ]

    result = rag_service.retrieve("điều khoản", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [1, 2]


def test_context_budget_keeps_whole_chunks_and_always_keeps_best_hit(qdrant, monkeypatch):
    monkeypatch.setattr(settings, "rag_max_context_chars", 30)
    qdrant.points = [
        _point("A" * 25, score=0.99, document_id=1),
        _point("B" * 20, score=0.98, document_id=2),
        _point("C" * 10, score=0.97, document_id=3),
    ]

    result = rag_service.retrieve("tiện ích", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [1]
    assert result[0]["content"] == "A" * 25


@pytest.fixture
def cohere_rerank(qdrant, monkeypatch):
    """Bật rerank và thay lời gọi API bằng hàm giả, ghi lại tham số để test soi."""
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "cohere_api_key", "test-key")
    calls = []

    def _fake_rerank(query, documents, *, top_n=None):
        calls.append({"query": query, "documents": documents, "top_n": top_n})
        return [(index, 1.0 - index * 0.1) for index in reversed(range(len(documents)))]

    monkeypatch.setattr(rag_service, "cohere_rerank", _fake_rerank)
    return calls


def test_cohere_rerank_reorders_over_vector_score(cohere_rerank, qdrant):
    """Cross-encoder thắng điểm vector: đó là lý do tồn tại của bước rerank."""
    qdrant.points = [
        _point("Tiện ích nội khu.", score=0.95, document_id=1),
        _point("Giá căn 2PN là 3.6 tỷ.", score=0.60, document_id=2),
    ]

    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [2, 1]


def test_cohere_rerank_receives_query_and_contents(cohere_rerank, qdrant):
    qdrant.points = [_point("Giá căn 2PN là 3.6 tỷ.", score=0.60, document_id=2)]

    rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert cohere_rerank[0]["query"] == "Giá căn 2PN?"
    assert cohere_rerank[0]["documents"] == ["Giá căn 2PN là 3.6 tỷ."]


def test_cohere_rerank_score_replaces_vector_score(cohere_rerank, qdrant):
    """Điểm trả về là relevance của cross-encoder, không phải cosine đã rescale."""
    qdrant.points = [_point("Giá căn 2PN là 3.6 tỷ.", score=0.60, document_id=2)]

    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert result[0]["score"] == 1.0


def test_cohere_failure_falls_back_to_heuristic(qdrant, monkeypatch):
    """Cohere sập thì chất lượng giảm, nhưng Sale vẫn phải nhận được câu trả lời."""
    monkeypatch.setattr(settings, "rerank_enabled", True)

    def _boom(query, documents, *, top_n=None):
        raise CohereRerankError("Cohere down")

    monkeypatch.setattr(rag_service, "cohere_rerank", _boom)
    qdrant.points = [
        _point("Căn 3PN diện tích lớn, giá 5.2 tỷ.", score=0.90, document_id=1),
        _point("Căn 2PN giá 3.6 tỷ.", score=0.86, document_id=2),
    ]

    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert result[0]["document_id"] == 2


def test_rerank_disabled_never_calls_cohere(qdrant, monkeypatch):
    monkeypatch.setattr(settings, "rerank_enabled", False)
    called = []
    monkeypatch.setattr(
        rag_service,
        "cohere_rerank",
        lambda query, documents, *, top_n=None: called.append(query) or [],
    )
    qdrant.points = [_point("Giá căn 2PN là 3.6 tỷ.", score=0.60, document_id=2)]

    rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert called == []


def test_rerank_enabled_without_api_key_uses_local_ranker(qdrant, monkeypatch):
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "cohere_api_key", "test-key")
    monkeypatch.setattr(settings, "cohere_api_key", "")
    called = []
    monkeypatch.setattr(rag_service, "cohere_rerank", lambda *_a, **_kw: called.append(True) or [])
    qdrant.points = [_point("Căn 2PN giá 3.6 tỷ.", score=0.60, document_id=2)]

    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert called == []
    assert [hit["document_id"] for hit in result] == [2]


@pytest.mark.parametrize(
    "invalid_result",
    [
        [(99, 0.9)],
        [(0, 0.9), (0, 0.8)],
        [(0, float("nan"))],
    ],
)
def test_invalid_cohere_output_falls_back_without_crashing(qdrant, monkeypatch, invalid_result):
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "cohere_api_key", "test-key")
    monkeypatch.setattr(rag_service, "cohere_rerank", lambda *_args, **_kwargs: invalid_result)
    qdrant.points = [_point("Căn 2PN giá 3.6 tỷ.", score=0.60, document_id=2)]

    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [2]


def test_cohere_rerank_applies_to_hybrid_results(hybrid_qdrant, monkeypatch):
    """Hybrid bỏ qua heuristic vì RRF đã xếp hạng, nhưng cross-encoder thì vẫn chạy."""
    monkeypatch.setattr(settings, "rerank_enabled", True)
    monkeypatch.setattr(settings, "cohere_api_key", "test-key")
    monkeypatch.setattr(
        rag_service,
        "cohere_rerank",
        lambda query, documents, *, top_n=None: [
            (index, 1.0 - index * 0.1) for index in reversed(range(len(documents)))
        ],
    )
    hybrid_qdrant.points = [
        _point("Tiện ích nội khu.", score=0.9, document_id=1),
        _point("Giá căn 2PN là 3.6 tỷ.", score=0.5, document_id=2),
    ]

    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [2, 1]


def test_missing_collection_returns_empty_list(qdrant):
    """Chưa ai upload tài liệu — Empty State, không phải lỗi hệ thống."""
    qdrant.exists = False

    assert rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL) == []
    assert qdrant.query_calls == []


def test_blank_query_returns_empty_without_calling_qdrant(qdrant):
    assert rag_service.retrieve("   ", DocumentVisibility.INTERNAL) == []
    assert qdrant.query_calls == []


def test_non_positive_top_k_returns_empty(qdrant):
    assert rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL, top_k=0) == []
    assert qdrant.query_calls == []


def test_embedding_failure_becomes_retrieval_error(qdrant, monkeypatch):
    def _boom(query):
        raise GeminiEmbeddingError("Gemini down")

    monkeypatch.setattr(rag_service, "embed_query", _boom)

    with pytest.raises(rag_service.RetrievalError, match="Could not embed"):
        rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)


def test_qdrant_failure_becomes_retrieval_error(qdrant, monkeypatch):
    def _boom(**kwargs):
        raise ConnectionError("Qdrant unreachable")

    monkeypatch.setattr(qdrant, "query_points", _boom)

    with pytest.raises(rag_service.RetrievalError, match="Could not query Qdrant"):
        rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)


def test_filter_is_a_qdrant_filter_object(qdrant):
    """Giữ đúng kiểu của qdrant-client để không vỡ khi nâng version."""
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    assert isinstance(qdrant.query_calls[0]["query_filter"], models.Filter)


def test_dense_only_names_the_dense_vector(qdrant):
    """Collection có nhiều vector có tên: thiếu `using` thì Qdrant không biết tìm ở đâu."""
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    assert qdrant.query_calls[0]["using"] == "dense"
    assert "prefetch" not in qdrant.query_calls[0]


def test_hybrid_query_builds_prefetch_and_rrf_fusion(hybrid_qdrant):
    rag_service.retrieve("giá căn 2PN", DocumentVisibility.INTERNAL, top_k=5)

    call = hybrid_qdrant.query_calls[0]
    prefetch = call["prefetch"]

    assert [branch.using for branch in prefetch] == ["dense", "sparse"]
    assert prefetch[0].query == [0.1, 0.2, 0.3]
    assert prefetch[1].query.indices == [7, 9]
    assert isinstance(call["query"], models.FusionQuery)
    assert call["query"].fusion == models.Fusion.RRF


def test_hybrid_applies_rbac_filter_to_every_branch(hybrid_qdrant):
    """Lọc sau khi hợp nhất là quá muộn — nhánh đã xếp hạng bằng tài liệu không được đọc."""
    rag_service.retrieve("giá căn hộ", DocumentVisibility.PUBLIC, project_id="the-palma")

    call = hybrid_qdrant.query_calls[0]
    for branch in call["prefetch"]:
        assert _visibility_values({"query_filter": branch.filter}) == ["public"]
    assert _visibility_values(call) == ["public"]


def test_hybrid_overfetches_on_both_branches(hybrid_qdrant):
    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL, top_k=5)

    call = hybrid_qdrant.query_calls[0]
    expected = 5 * rag_service.OVERFETCH_FACTOR
    assert [branch.limit for branch in call["prefetch"]] == [expected, expected]
    assert call["limit"] == expected


def test_hybrid_keeps_rrf_scores_but_exact_identifier_gets_final_priority(hybrid_qdrant, monkeypatch):
    """Keep raw RRF scores, while an exact code match acts as a final safety layer."""
    monkeypatch.setattr(settings, "rerank_enabled", False)
    hybrid_qdrant.points = [
        _point("Chính sách chung, không có mã căn.", score=0.032, document_id=1),
        _point("Căn 2PN mã OP3-CT1-0504.", score=0.016, document_id=2),
    ]

    result = rag_service.retrieve("giá căn 2PN", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result] == [2, 1]
    assert result[0]["score"] == 0.016


def test_sparse_embedding_failure_falls_back_to_dense_only(hybrid_qdrant, monkeypatch):
    """Mất kênh từ khoá thì câu trả lời kém sắc hơn, nhưng Sale vẫn phải có câu trả lời."""

    def _boom(query):
        raise rag_service.SparseEmbeddingError("model missing")

    monkeypatch.setattr(rag_service, "embed_query_sparse", _boom)
    hybrid_qdrant.points = [_point("Giá căn hộ.", score=1.0)]

    result = rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    assert len(result) == 1
    assert "prefetch" not in hybrid_qdrant.query_calls[0]
    assert hybrid_qdrant.query_calls[0]["using"] == "dense"


def test_disabled_flag_never_embeds_the_sparse_query(qdrant, monkeypatch):
    calls = []
    monkeypatch.setattr(rag_service, "embed_query_sparse", lambda query: calls.append(query))

    rag_service.retrieve("giá căn hộ", DocumentVisibility.INTERNAL)

    assert calls == []
    assert "prefetch" not in qdrant.query_calls[0]


@pytest.fixture
def live_qdrant(monkeypatch):
    from qdrant_client import QdrantClient

    from backend.services import vector_store_service

    client = QdrantClient(":memory:")
    monkeypatch.setattr(rag_service, "get_qdrant_client", lambda: client)
    monkeypatch.setattr(vector_store_service, "get_qdrant_client", lambda: client)
    monkeypatch.setattr(settings, "qdrant_collection", "itest_documents")
    monkeypatch.setattr(settings, "embedding_dimensions", 3)
    monkeypatch.setattr(rag_service, "embed_query", lambda query: [1.0, 0.0, 0.0])

    from backend.services.chunking_service import DocumentChunk

    vector_store_service.index_document_chunks(
        document_id=1,
        title="bang-gia.pdf",
        project_id="ocean-park-3",
        visibility="internal",
        chunks=[DocumentChunk(index=0, text="Căn 2PN giá 3.6 tỷ.", page=2)],
        vectors=[[1.0, 0.0, 0.0]],
        sparse_vectors=embed_documents_sparse(["Căn 2PN giá 3.6 tỷ."]),
        review_status="approved",
        category="price_list",
    )
    vector_store_service.index_document_chunks(
        document_id=2,
        title="cong-khai.pdf",
        project_id="ocean-park-3",
        visibility="public",
        chunks=[DocumentChunk(index=0, text="Tiện ích nội khu.", page=1)],
        vectors=[[0.9, 0.1, 0.0]],
        sparse_vectors=embed_documents_sparse(["Tiện ích nội khu."]),
        review_status="approved",
        category="subdivision_info",
    )
    return client


def test_live_internal_clearance_reads_both_tiers(live_qdrant):
    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL)

    assert sorted(hit["document_id"] for hit in result) == [1, 2]


def test_live_public_clearance_cannot_read_internal_document(live_qdrant):
    """Lớp RBAC thứ hai chạy thật: tài liệu nội bộ không được lọt vào context."""
    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.PUBLIC)

    assert [hit["document_id"] for hit in result] == [2]


def test_live_project_filter_excludes_other_projects(live_qdrant):
    assert rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL, project_id="khong-ton-tai") == []


def test_live_project_scope_also_includes_global_documents(live_qdrant):
    from backend.services import vector_store_service
    from backend.services.chunking_service import DocumentChunk

    vector_store_service.index_document_chunks(
        document_id=3,
        title="huong-dan-chung.pdf",
        project_id=None,
        visibility="public",
        chunks=[DocumentChunk(index=0, text="Hướng dẫn giao dịch chung.", page=1)],
        vectors=[[1.0, 0.0, 0.0]],
        sparse_vectors=embed_documents_sparse(["Hướng dẫn giao dịch chung."]),
        review_status="approved",
        category="internal_guide",
    )

    result = rag_service.retrieve("Hướng dẫn giao dịch", DocumentVisibility.INTERNAL, project_id="khong-ton-tai")

    assert [hit["document_id"] for hit in result] == [3]


def test_live_carries_page_for_citation(live_qdrant):
    """Không có page thì bước Generate không trích nguồn tới số trang được."""
    result = rag_service.retrieve("Giá căn 2PN?", DocumentVisibility.INTERNAL, project_id="ocean-park-3")

    assert result[0]["page"] == 2
    assert result[0]["title"] == "bang-gia.pdf"


@pytest.fixture
def live_hybrid_qdrant(monkeypatch):
    """Hai tài liệu dựng riêng cho phép so sánh trực tiếp hybrid với dense-only.

    Tài liệu 1 nằm đúng hướng vector truy vấn nhưng KHÔNG chứa mã căn được hỏi.
    Tài liệu 2 lệch hướng vector nhưng chứa đúng mã đó — chỉ BM25 mới thấy được.
    """
    from qdrant_client import QdrantClient

    from backend.services import vector_store_service
    from backend.services.chunking_service import DocumentChunk

    client = QdrantClient(":memory:")
    monkeypatch.setattr(rag_service, "get_qdrant_client", lambda: client)
    monkeypatch.setattr(vector_store_service, "get_qdrant_client", lambda: client)
    monkeypatch.setattr(settings, "qdrant_collection", "itest_hybrid")
    monkeypatch.setattr(settings, "embedding_dimensions", 3)
    monkeypatch.setattr(rag_service, "embed_query", lambda query: [1.0, 0.0, 0.0])

    semantic_text = "Bảng giá các căn hộ hai phòng ngủ của dự án."
    keyword_text = "Căn OP3-CT1-0504 đã có chủ."

    vector_store_service.index_document_chunks(
        document_id=1,
        title="ngu-nghia.pdf",
        project_id="ocean-park-3",
        visibility="internal",
        chunks=[DocumentChunk(index=0, text=semantic_text, page=1)],
        vectors=[[1.0, 0.0, 0.0]],
        sparse_vectors=embed_documents_sparse([semantic_text]),
        review_status="approved",
        category="price_list",
    )
    vector_store_service.index_document_chunks(
        document_id=2,
        title="tu-khoa.pdf",
        project_id="ocean-park-3",
        visibility="internal",
        chunks=[DocumentChunk(index=0, text=keyword_text, page=1)],
        vectors=[[0.0, 1.0, 0.0]],
        sparse_vectors=embed_documents_sparse([keyword_text]),
        review_status="approved",
        category="inventory_snapshot",
    )
    return client


def test_live_dense_candidates_get_exact_identifier_safety_ranking(live_hybrid_qdrant, monkeypatch):
    """Dense finds both candidates; final selection prevents the wrong unit code winning."""
    monkeypatch.setattr(settings, "hybrid_search_enabled", False)
    monkeypatch.setattr(settings, "rerank_enabled", False)

    result = rag_service.retrieve("Căn OP3-CT1-0504 còn không?", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result][0] == 2


def test_live_rrf_promotes_exact_keyword_match(live_hybrid_qdrant, monkeypatch):
    """Cùng câu hỏi, bật hybrid: kênh BM25 kéo tài liệu chứa đúng mã căn lên đầu.

    Rerank tắt để bài test này chỉ đo hiệu ứng của RRF, tách biệt khỏi cross-encoder.
    """
    monkeypatch.setattr(settings, "hybrid_search_enabled", True)
    monkeypatch.setattr(settings, "rerank_enabled", False)

    result = rag_service.retrieve("Căn OP3-CT1-0504 còn không?", DocumentVisibility.INTERNAL)

    assert [hit["document_id"] for hit in result][0] == 2


def test_live_hybrid_still_enforces_rbac(live_hybrid_qdrant, monkeypatch):
    """Thêm một kênh truy vấn không được phép mở thêm đường vòng qua RBAC."""
    monkeypatch.setattr(settings, "hybrid_search_enabled", True)
    monkeypatch.setattr(settings, "rerank_enabled", False)

    assert rag_service.retrieve("Căn OP3-CT1-0504 còn không?", DocumentVisibility.PUBLIC) == []
