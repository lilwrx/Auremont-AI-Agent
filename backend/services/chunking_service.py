import re
from dataclasses import dataclass
from typing import Any

from backend.services.parser_service import ParsedSection
from backend.utils.text import strip_diacritics

SECTION_BOUNDARY_RE = re.compile(
    r"\n\s*\n|(?=\n\s*(?:CHƯƠNG\s+[IVXLCDM0-9]+\b|ĐIỀU\s+\d+\b|"
    r"[IVXLCDM]+\.\s+|\d+\.\s+|[a-zđ]\.\s+))",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class DocumentChunk:
    """A block of text ready to be embedded and stored in Qdrant."""

    index: int
    text: str
    page: int | None
    content_type: str = "prose"
    y_position: float | None = None
    category: str | None = None
    section_index: int | None = None


def chunk_sections(
    sections: list[ParsedSection],
    *,
    chunk_chars: int = 3200,
    overlap_chars: int = 400,
    document_category: str | None = None,
) -> list[DocumentChunk]:
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be greater than 0")

    if overlap_chars < 0 or overlap_chars >= chunk_chars:
        raise ValueError("overlap_chars must be >= 0 and smaller than chunk_chars")

    chunks: list[DocumentChunk] = []

    category = str(document_category or "").lower()
    splitter = _split_legal_text if category == "legal_document" else _split_text

    for section in sections:
        texts = (
            _split_table(section.text, chunk_chars=chunk_chars)
            if section.content_type == "table"
            else splitter(
                section.text,
                chunk_chars=chunk_chars,
                overlap_chars=overlap_chars,
                table_mode=category in {"price_list", "inventory_snapshot", "payment_schedule"},
            )
        )
        for text in texts:
            chunks.append(
                DocumentChunk(
                    index=len(chunks),
                    text=text,
                    page=section.page,
                    content_type=section.content_type,
                    y_position=_estimate_y_position(text, section),
                )
            )

    return chunks


def chunk_sections_by_classification(
    sections: list[ParsedSection],
    *,
    primary_category: str,
    section_classifications: list[dict[str, Any]] | None = None,
    chunk_chars: int = 3200,
    overlap_chars: int = 400,
) -> list[DocumentChunk]:
    """Chunk a mixed document once while preserving a category per content unit.

    The classifier sees deterministic generic chunks identified by ``section_index``.
    Once Admin approves those assignments, each generic unit is optionally passed
    through the category-aware splitter (legal clauses, tabular price/payment rows),
    and every resulting child keeps the unit's business category. No source text is
    embedded twice.
    """

    assignments: dict[int, str] = {}
    for item in section_classifications or []:
        try:
            section_index = int(str(item.get("section_index")))
        except (AttributeError, TypeError, ValueError):
            continue
        category = str(item.get("category") or "").strip()
        if section_index >= 0 and category:
            assignments[section_index] = category

    if not assignments:
        chunks = chunk_sections(
            sections,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
            document_category=primary_category,
        )
        return [
            DocumentChunk(
                index=chunk.index,
                text=chunk.text,
                page=chunk.page,
                content_type=chunk.content_type,
                y_position=chunk.y_position,
                category=primary_category,
                section_index=chunk.index,
            )
            for chunk in chunks
        ]

    base_units = chunk_sections(
        sections,
        chunk_chars=chunk_chars,
        overlap_chars=overlap_chars,
        document_category=None,
    )
    result: list[DocumentChunk] = []
    for unit in base_units:
        category = assignments.get(unit.index, primary_category)
        children = chunk_sections(
            [
                ParsedSection(
                    text=unit.text,
                    page=unit.page,
                    content_type=unit.content_type,
                )
            ],
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
            document_category=category,
        )
        for child in children:
            result.append(
                DocumentChunk(
                    index=len(result),
                    text=child.text,
                    page=child.page,
                    content_type=child.content_type,
                    y_position=child.y_position if child.y_position is not None else unit.y_position,
                    category=category,
                    section_index=unit.index,
                )
            )
    return result


def _split_table(markdown: str, *, chunk_chars: int) -> list[str]:
    """Split a markdown table into whole-table or row-batch chunks.

    Kept as a whole table whenever it fits, so retrieval returns one complete,
    self-contained table. Larger tables (e.g. an 11-row payment schedule) are cut
    into row-batches instead — separate from _split_text/_append_block, which are
    heading-breadcrumb oriented rather than table-row oriented.
    """
    if not markdown.strip():
        return []

    if len(markdown) <= chunk_chars:
        return [markdown]

    lines = [line for line in markdown.splitlines() if line.strip()]
    batches: list[str] = []
    current: list[str] = []

    for line in lines:
        candidate = "\n".join(current + [line])
        if len(candidate) > chunk_chars and current:
            batches.append("\n".join(current))
            current = [line]
        else:
            current.append(line)

    if current:
        batches.append("\n".join(current))

    return batches


def _estimate_y_position(chunk_text: str, section: ParsedSection) -> float | None:
    """Where roughly does this chunk sit vertically on its source page?

    A chunk's text is not always a clean substring of `section.text` — `_start_chunk`
    above prepends a heading breadcrumb, and can prepend overlap carried over from the
    PREVIOUS chunk, both of which are real page content but not from where this chunk
    visually starts. So this searches line by line for the first reasonably long,
    unambiguous line (short lines match too many places on a dense policy page) and uses
    *its* position — skipping past a prepended breadcrumb naturally, since headings are
    short and this only matches lines with real length.
    """
    if not section.block_offsets:
        return None

    for line in chunk_text.splitlines():
        line = line.strip()
        if len(line) < 15:
            continue
        offset = section.text.find(line)
        if offset >= 0:
            return _y_for_offset(offset, section.block_offsets)

    return None


def _y_for_offset(offset: int, block_offsets: tuple[tuple[int, float], ...]) -> float:
    """The Y of the last breakpoint at or before `offset` — block_offsets is sorted
    ascending by offset, so this is "which visual block does this character fall in"."""
    y = block_offsets[0][1]
    for bp_offset, bp_y in block_offsets:
        if bp_offset > offset:
            break
        y = bp_y
    return y


ROMAN_HEADING_RE = re.compile(r"^[IVXLCDM]+\.\s+[^\n]+$", re.IGNORECASE)
NUMBER_HEADING_RE = re.compile(r"^\d+\.\s+[^\n]+$")
ALPHA_HEADING_RE = re.compile(r"^[a-zđ]\.\s+[^\n]+$", re.IGNORECASE)
CHAPTER_HEADING_RE = re.compile(r"^CHƯƠNG\s+[IVXLCDM0-9]+\b[^\n]*$", re.IGNORECASE)
ARTICLE_HEADING_RE = re.compile(r"^ĐIỀU\s+\d+\b[^\n]*$", re.IGNORECASE)
TABLE_ROW_RE = re.compile(r"^\s*\|.*\|\s*$")
TABULAR_ROW_RE = re.compile(r"^\s*\S.*(?:\t|\s{2,})\S.*$")
BULLET_RE = re.compile(r"^\s*(?:[-•*]|\(?[a-zđ]\)|\d+\))\s+", re.IGNORECASE)

LEGAL_ARTICLE_RE = re.compile(r"^dieu\s+(\d+[a-z]?)\s*[.:\-]?\s*(.*)$", re.IGNORECASE)
LEGAL_CHAPTER_RE = re.compile(r"^(chuong|phan|muc|tieu muc)\s+([ivxlcdm0-9]+)\b.*$", re.IGNORECASE)
LEGAL_CLAUSE_RE = re.compile(r"^(\d+)\s*[.)]\s+\S.*$")
LEGAL_POINT_RE = re.compile(r"^([a-z]|d)\s*[.)]\s+\S.*$", re.IGNORECASE)


def _split_text(
    text: str,
    *,
    chunk_chars: int,
    overlap_chars: int,
    table_mode: bool = False,
) -> list[str]:
    """Split text while maintaining a 3-level context breadcrumb (I. -> 1. -> a.)."""
    if not text or not text.strip():
        return []

    text = _normalise_extracted_text(text)
    raw_blocks = [block.strip() for block in SECTION_BOUNDARY_RE.split(text) if block.strip()]
    blocks = [item for block in raw_blocks for item in _separate_inline_headings(block)]

    result: list[str] = []
    current = ""

    roman_header = ""
    number_header = ""
    active_header = ""

    for block in blocks:
        if ROMAN_HEADING_RE.match(block) or CHAPTER_HEADING_RE.match(block):
            if current:
                result.append(current)
                current = ""
            roman_header = block
            number_header = ""
            continue

        if NUMBER_HEADING_RE.match(block) or ARTICLE_HEADING_RE.match(block):
            if current:
                result.append(current)
                current = ""
            number_header = block
            continue

        if ALPHA_HEADING_RE.match(block):
            if current:
                result.append(current)
                current = ""
            number_header = f"{number_header} > {block}" if number_header else block
            continue

        headers = [h for h in (roman_header, number_header) if h]
        active_header = " > ".join(headers) if headers else ""

        for logical_block in _split_logical_block(block, table_mode=table_mode):
            if table_mode and _is_table_block(logical_block):
                if current:
                    result.append(current)
                    current = ""
                result.extend(
                    _chunk_table_block(
                        logical_block,
                        active_header=active_header,
                        chunk_chars=chunk_chars,
                    )
                )
                continue
            current = _append_block(
                result=result,
                current=current,
                block=logical_block,
                active_header=active_header,
                chunk_chars=chunk_chars,
                overlap_chars=overlap_chars,
            )

    if not current:
        trailing_headers = [header for header in (roman_header, number_header) if header]
        trailing_header = " > ".join(trailing_headers)

        if trailing_header:
            current = trailing_header[:chunk_chars]

    if current:
        result.append(current)

    return result


def _append_block(
    *,
    result: list[str],
    current: str,
    block: str,
    active_header: str,
    chunk_chars: int,
    overlap_chars: int,
) -> str:
    """Append a block to the current chunk, splitting it further when needed."""
    remaining = block.strip()

    while remaining:
        if not current:
            current = _start_chunk(
                active_header=active_header,
                previous_chunk=result[-1] if result else "",
                chunk_chars=chunk_chars,
                overlap_chars=overlap_chars,
            )

        separator = "\n\n" if current else ""
        available = chunk_chars - len(current) - len(separator)

        if available <= 0:
            result.append(current)
            current = ""
            continue

        piece, remaining = _take_prefix(remaining, available)
        current = f"{current}{separator}{piece}" if current else piece

        if remaining:
            result.append(current)
            current = ""

    return current


def _start_chunk(
    *,
    active_header: str,
    previous_chunk: str,
    chunk_chars: int,
    overlap_chars: int,
) -> str:
    """Start a new chunk, repeating the heading and overlap within the allowed limit."""
    header = active_header.strip()

    if len(header) >= chunk_chars:
        return header[:chunk_chars]

    overlap_budget = chunk_chars - len(header) - 2
    overlap = _tail(previous_chunk, min(overlap_chars, overlap_budget))

    if header and overlap:
        return f"{header}\n{overlap}"

    return header or overlap


def _take_prefix(text: str, limit: int) -> tuple[str, str]:
    """Take a prefix at a semantic boundary before falling back to a word cut."""
    if len(text) <= limit:
        return text, ""

    newline_boundary = text.rfind("\n", 0, limit + 1)
    sentence_boundary = max(
        text.rfind(". ", 0, limit + 1),
        text.rfind("; ", 0, limit + 1),
        text.rfind(": ", 0, limit + 1),
    )
    space_boundary = text.rfind(" ", 0, limit + 1)
    boundary = max(newline_boundary, sentence_boundary + 1, space_boundary)

    if boundary <= 0:
        boundary = limit

    prefix = text[:boundary].strip()
    remainder = text[boundary:].strip()

    if not prefix:
        prefix = text[:limit].strip()
        remainder = text[limit:].strip()

    return prefix, remainder


def _normalise_extracted_text(text: str) -> str:
    """Make PDF extraction stable without flattening legal/article structure.

    Some PDFs use non-breaking spaces and produce several empty lines around a
    page header/footer.  We retain all meaningful lines (including legal numbers
    and tables) while collapsing that extraction noise.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_logical_block(block: str, *, table_mode: bool = False) -> list[str]:
    """Keep tables and lists intact as units before character-level splitting.

    A policy PDF usually contains discount/payment tables and nested bullet terms.
    Treating each row/item as a unit gives retrieval a complete business rule
    instead of an orphan amount, while `_append_block` still enforces the size cap.
    """
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return []

    groups: list[list[str]] = []
    current: list[str] = []
    current_kind = "text"

    for line in lines:
        kind = (
            "table"
            if TABLE_ROW_RE.match(line) or (table_mode and TABULAR_ROW_RE.match(line))
            else "bullet"
            if BULLET_RE.match(line)
            else "text"
        )
        if current and kind != current_kind and (kind != "text" or current_kind != "text"):
            groups.append(current)
            current = []
        current.append(line)
        current_kind = kind

    if current:
        groups.append(current)

    return ["\n".join(group) for group in groups]


def _is_table_block(block: str) -> bool:
    lines = [line for line in block.splitlines() if line.strip()]
    return bool(lines) and all(TABLE_ROW_RE.match(line) or TABULAR_ROW_RE.match(line) for line in lines)


def _chunk_table_block(
    block: str,
    *,
    active_header: str,
    chunk_chars: int,
) -> list[str]:
    """Split only between rows and repeat the column header in every chunk.

    A single very wide row may exceed ``chunk_chars``. Keeping a unit code, its
    price and the column names together is safer than satisfying a soft size
    target by cutting a business record in half.
    """
    rows = [line.strip() for line in block.splitlines() if line.strip()]
    if not rows:
        return []

    header_count = 2 if len(rows) > 1 and re.search(r"---|===", rows[1]) else 1
    header_rows = rows[:header_count]
    data_rows = rows[header_count:]
    prefix = "\n".join(part for part in (active_header.strip(), "\n".join(header_rows)) if part)
    if not data_rows:
        return [prefix[:chunk_chars]] if prefix else []

    chunks: list[str] = []
    current = prefix
    for row in data_rows:
        candidate = f"{current}\n{row}" if current else row
        if len(candidate) <= chunk_chars:
            current = candidate
            continue
        if current and current != prefix:
            chunks.append(current)
            current = prefix
        candidate = f"{current}\n{row}" if current else row
        if len(candidate) > chunk_chars:
            chunks.append(candidate)
            current = prefix
        else:
            current = candidate
    if current and (current != prefix or not chunks):
        chunks.append(current)
    return chunks


def _split_legal_text(
    text: str,
    *,
    chunk_chars: int,
    overlap_chars: int,
    table_mode: bool = False,
) -> list[str]:
    """Split Vietnamese law on Article/Clause/Point boundaries.

    No raw overlap is copied across articles because text from one article inside
    another article's chunk changes legal meaning. Explicit breadcrumbs provide
    the necessary context instead.
    """
    del overlap_chars, table_mode
    lines = [line.strip() for line in _normalise_extracted_text(text).splitlines() if line.strip()]
    if not lines:
        return []

    chapter = article = clause = point = ""
    chunks: list[str] = []
    body: list[str] = []

    def flush() -> None:
        nonlocal body
        if not body:
            return
        breadcrumb = " > ".join(item for item in (chapter, article, clause, point) if item)
        chunks.extend(_pack_with_header("\n".join(body), breadcrumb, chunk_chars))
        body = []

    for line in lines:
        key = strip_diacritics(line).lower()
        if LEGAL_CHAPTER_RE.match(key):
            flush()
            chapter, article, clause, point = line, "", "", ""
            continue
        if LEGAL_ARTICLE_RE.match(key):
            flush()
            article, clause, point = line, "", ""
            continue
        clause_match = LEGAL_CLAUSE_RE.match(key)
        if clause_match:
            flush()
            clause, point = f"Khoản {clause_match.group(1)}", ""
            body.append(line)
            continue
        point_match = LEGAL_POINT_RE.match(key)
        if point_match:
            flush()
            point = f"Điểm {point_match.group(1)}"
            body.append(line)
            continue
        body.append(line)
    flush()

    if not chunks:
        heading = " > ".join(item for item in (chapter, article, clause, point) if item)
        return [heading[:chunk_chars]] if heading else []
    return chunks


def _pack_with_header(content: str, header: str, chunk_chars: int) -> list[str]:
    result: list[str] = []
    remaining = content
    while remaining:
        prefix = header[:chunk_chars]
        available = chunk_chars - len(prefix) - (2 if prefix else 0)
        if available <= 0:
            return [prefix]
        piece, remaining = _take_prefix(remaining, available)
        result.append(f"{prefix}\n\n{piece}" if prefix else piece)
    return result


def _separate_inline_headings(block: str) -> list[str]:
    """Split a PDF block when its heading and body share the same paragraph.

    PyMuPDF commonly returns `I. ...` followed by its body on the next line,
    without a blank paragraph.  Splitting it here lets the heading become a
    breadcrumb instead of embedding it only in the first chunk of a section.
    """
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    if not lines:
        return []

    parts: list[str] = []
    body: list[str] = []
    for line in lines:
        if _is_heading_line(line):
            if body:
                parts.append("\n".join(body))
                body = []
            parts.append(line)
        else:
            body.append(line)
    if body:
        parts.append("\n".join(body))
    return parts


def _is_heading_line(line: str) -> bool:
    if CHAPTER_HEADING_RE.match(line) or ARTICLE_HEADING_RE.match(line):
        return True
    if ROMAN_HEADING_RE.match(line):
        return True
    return len(line) <= 100 and (NUMBER_HEADING_RE.match(line) is not None or ALPHA_HEADING_RE.match(line) is not None)


def _tail(text: str, limit: int) -> str:
    """Take a suffix to use as overlap, preferring to start at a word boundary."""
    if limit <= 0 or not text:
        return ""

    if len(text) <= limit:
        return text.strip()

    tail = text[-limit:]
    first_space = tail.find(" ")
    first_newline = tail.find("\n")
    boundaries = [item for item in (first_space, first_newline) if item >= 0]

    if boundaries:
        tail = tail[min(boundaries) + 1 :]

    return tail.strip()
