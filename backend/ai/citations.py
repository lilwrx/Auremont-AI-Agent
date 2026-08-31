"""Turn retrieved chunks into the citation list shown under an answer."""

from collections import Counter


def build_citations(docs: list[dict]) -> list[dict]:
    """Normalise citations into the exact shape of the `Citation` schema.

    One chip per file, not per page: retrieval routinely returns several chunks of the
    same PDF, and listing "Bảng giá · tr.1, Bảng giá · tr.2, Bảng giá · tr.10" told the Sale
    nothing they could act on while crowding the answer. The file name is the useful part.

    Deduplication is by `document_id`, not by title. Two genuinely different documents can
    share a file name, and collapsing them keeps whichever ranked highest — so the chip
    opens the wrong file, silently, which is the one failure a citation must never have.
    Same-titled documents are rare by construction (identical content is quarantined at
    ingestion, superseded versions are filtered out by `is_current`, and `_citations_for`
    drops citations entirely when the hits span several projects), but "rare" is not
    "impossible" and the failure is invisible when it happens.

    Because that leaves the possibility of two chips reading the same name, a `qualifier`
    is attached to each side of a collision — the page they were cited from, or the
    document id when even that matches. Two chips a Sale cannot tell apart are no more
    usable than one chip pointing at the wrong file; both break the same promise.

    Filtering is mandatory: `document_id` from a Qdrant payload may be None, while
    `Citation` declares a non-nullable `document_id: int` — letting one through becomes a
    ValidationError 500 while serializing the response. `content`/`score` are dropped too,
    since the schema does not accept those fields.

    `page` (and `y_position`, same reasoning) is kept from the FIRST chunk seen for that
    document — `docs` arrives already ordered by `_rerank`, so that's the chunk the answer
    is most likely actually drawing from. It lets the citation chip open straight to that
    spot instead of just the top of the file; later chunks of the same file (different
    pages) are still collapsed away.
    """
    citations: list[dict] = []
    seen: set[int] = set()

    for doc in docs:
        document_id = doc.get("document_id")
        if document_id is None or document_id in seen:
            continue
        seen.add(document_id)

        citations.append(
            {
                "document_id": document_id,
                "title": doc.get("title") or "Tài liệu",
                "qualifier": None,
                "page": doc.get("page"),
                "y_position": doc.get("y_position"),
            }
        )

    _qualify_duplicate_titles(citations)
    return citations


def _qualify_duplicate_titles(citations: list[dict]) -> None:
    """Give every citation in a same-title group something that tells it apart, in place.

    Prefers the page number, which also says where in the file the answer came from. Falls
    back to the document id when the pages match too — ugly, but unambiguous, and it only
    ever surfaces for two same-named files cited from the same page.
    """
    title_counts = Counter(citation["title"] for citation in citations)
    duplicated = {title for title, count in title_counts.items() if count > 1}
    if not duplicated:
        return

    for title in duplicated:
        group = [citation for citation in citations if citation["title"] == title]
        pages = [citation["page"] for citation in group]
        pages_are_distinct = len(set(pages)) == len(pages) and all(page is not None for page in pages)

        for citation in group:
            citation["qualifier"] = f"tr.{citation['page']}" if pages_are_distinct else f"#{citation['document_id']}"
