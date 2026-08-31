"""_citations_for: drop citations when retrieval span multiple unrelated projects.

An unscoped search that returns top hits from 2+ different projects is the same shape of
query that makes the model ask "which project do you mean?" instead of answering from any
of them — citing files from projects the reply never engaged with would be misleading.
"""

from backend.services.agent_pipeline import _citations_for


def _doc(
    document_id: int,
    title: str,
    project_id: str | None,
    *,
    page: int = 1,
    content: str = "...",
    score: float = 0.0,
) -> dict:
    return {
        "document_id": document_id,
        "title": title,
        "content": content,
        "page": page,
        "project_id": project_id,
        "score": score,
    }


def test_single_project_keeps_citations():
    docs = [_doc(1, "bang-gia.pdf", "the-beverly"), _doc(2, "chinh-sach.docx", "the-beverly")]

    assert _citations_for(docs) == [
        {"document_id": 1, "title": "bang-gia.pdf", "qualifier": None, "page": 1, "y_position": None},
        {"document_id": 2, "title": "chinh-sach.docx", "qualifier": None, "page": 1, "y_position": None},
    ]


def test_multiple_projects_drops_citations():
    docs = [_doc(1, "beverly.pdf", "the-beverly"), _doc(2, "zurich.pdf", "the-zurich")]

    assert _citations_for(docs) == []


def test_missing_project_id_is_not_treated_as_ambiguous():
    """A doc with no project_id (company-wide policy, applies everywhere) shouldn't by
    itself count as a second "project" alongside a real one."""
    docs = [_doc(1, "bang-gia.pdf", "the-beverly"), _doc(2, "quy-dinh-chung.pdf", None)]

    assert _citations_for(docs) == [
        {"document_id": 1, "title": "bang-gia.pdf", "qualifier": None, "page": 1, "y_position": None},
        {"document_id": 2, "title": "quy-dinh-chung.pdf", "qualifier": None, "page": 1, "y_position": None},
    ]


def test_citation_page_is_selected_from_answer_evidence_not_first_hit():
    docs = [
        _doc(
            1,
            "bang-gia.pdf",
            "the-palma",
            page=2,
            content="Tổng quan căn hộ 1PN, 2PN, 3PN.",
            score=0.95,
        ),
        _doc(
            1,
            "bang-gia.pdf",
            "the-palma",
            page=4,
            content="Căn 2PN có diện tích 64,3-69,9 m2 và giá 5,774-7,273 tỷ đồng.",
            score=0.60,
        ),
    ]

    citations = _citations_for(
        docs,
        answer="Căn 2PN rộng 64,3-69,9 m2, giá khoảng 5,774-7,273 tỷ đồng.",
    )

    assert citations[0]["page"] == 4


def test_citation_ranking_without_answer_preserves_retrieval_order():
    docs = [
        _doc(1, "bang-gia.pdf", "the-palma", page=2, score=0.95),
        _doc(1, "bang-gia.pdf", "the-palma", page=4, score=0.60),
    ]

    citations = _citations_for(docs)

    assert citations[0]["page"] == 2
