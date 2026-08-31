"""build_citations: per-document dedup that keeps the first chunk's page/Y position.

A citation carries the product's core promise — the Sale clicks it to check what they are
about to tell a customer. Two ways to break that promise are covered here: a chip that
opens the wrong file, and two chips the Sale cannot tell apart.
"""

from backend.ai.citations import build_citations


def test_dedupes_chunks_of_one_file_and_keeps_first_page():
    docs = [
        {"document_id": 1, "title": "bang-gia.pdf", "content": "...", "page": 3, "y_position": 120.5},
        {"document_id": 1, "title": "bang-gia.pdf", "content": "...", "page": 7, "y_position": 400.0},
    ]

    result = build_citations(docs)

    assert result == [{"document_id": 1, "title": "bang-gia.pdf", "qualifier": None, "page": 3, "y_position": 120.5}]


def test_drops_hits_with_no_document_id():
    docs = [{"document_id": None, "title": "no-id.pdf", "content": "...", "page": 1}]

    assert build_citations(docs) == []


def test_missing_page_and_y_position_stay_none():
    docs = [{"document_id": 2, "title": "policy.docx", "content": "..."}]

    result = build_citations(docs)

    assert result == [{"document_id": 2, "title": "policy.docx", "qualifier": None, "page": None, "y_position": None}]


class TestSameTitledDocuments:
    def test_each_document_keeps_its_own_citation(self):
        """Collapsing these kept whichever ranked higher, so the chip opened the wrong file."""
        docs = [
            {"document_id": 1, "title": "chinh-sach.pdf", "page": 2, "y_position": 100.0},
            {"document_id": 2, "title": "chinh-sach.pdf", "page": 5, "y_position": 250.0},
        ]

        result = build_citations(docs)

        assert [c["document_id"] for c in result] == [1, 2]

    def test_the_page_tells_them_apart(self):
        docs = [
            {"document_id": 1, "title": "chinh-sach.pdf", "page": 2, "y_position": 100.0},
            {"document_id": 2, "title": "chinh-sach.pdf", "page": 5, "y_position": 250.0},
        ]

        result = build_citations(docs)

        assert [c["qualifier"] for c in result] == ["tr.2", "tr.5"]

    def test_the_document_id_is_the_fallback_when_pages_match_too(self):
        docs = [
            {"document_id": 1, "title": "chinh-sach.pdf", "page": 2},
            {"document_id": 37, "title": "chinh-sach.pdf", "page": 2},
        ]

        result = build_citations(docs)

        assert [c["qualifier"] for c in result] == ["#1", "#37"]

    def test_a_missing_page_falls_back_rather_than_rendering_none(self):
        docs = [
            {"document_id": 1, "title": "chinh-sach.pdf", "page": None},
            {"document_id": 2, "title": "chinh-sach.pdf", "page": 5},
        ]

        result = build_citations(docs)

        assert [c["qualifier"] for c in result] == ["#1", "#2"]

    def test_the_title_itself_is_never_touched(self):
        """CitationList.tsx decides between the inline PDF preview and a new tab by testing
        that the title still ends in ".pdf" — appending the qualifier there would break it."""
        docs = [
            {"document_id": 1, "title": "chinh-sach.pdf", "page": 2},
            {"document_id": 2, "title": "chinh-sach.pdf", "page": 5},
        ]

        result = build_citations(docs)

        assert all(c["title"] == "chinh-sach.pdf" for c in result)

    def test_unique_titles_are_left_unqualified(self):
        """The common case must look exactly as it did before."""
        docs = [
            {"document_id": 1, "title": "bang-gia.pdf", "page": 2},
            {"document_id": 2, "title": "chinh-sach.pdf", "page": 5},
        ]

        result = build_citations(docs)

        assert [c["qualifier"] for c in result] == [None, None]

    def test_only_the_colliding_group_is_qualified(self):
        docs = [
            {"document_id": 1, "title": "chinh-sach.pdf", "page": 2},
            {"document_id": 2, "title": "chinh-sach.pdf", "page": 5},
            {"document_id": 3, "title": "bang-gia.pdf", "page": 9},
        ]

        result = build_citations(docs)

        assert [(c["document_id"], c["qualifier"]) for c in result] == [
            (1, "tr.2"),
            (2, "tr.5"),
            (3, None),
        ]
