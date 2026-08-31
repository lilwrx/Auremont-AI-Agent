"""Shared scope and state rules for the Admin document-coverage dashboard."""

import re
import unicodedata
from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from backend.core.enums import DocumentReviewStatus, DocumentStatus
from backend.models.document import Document
from backend.models.project import Project

CoverageState = Literal["ready", "pending_review", "unavailable", "missing"]

COVERAGE_CATEGORIES = (
    "subdivision_info",
    "sales_policy",
    "price_list",
    "floor_plan",
    "legal_document",
    "payment_schedule",
)


def canonical_scope_name(value: str) -> str:
    """Create an accent/case/punctuation-insensitive exact-match key."""

    decomposed = unicodedata.normalize("NFKD", value.casefold().replace("đ", "d"))
    without_marks = "".join(character for character in decomposed if not unicodedata.combining(character))
    return " ".join(re.findall(r"[a-z0-9]+", without_marks))


def project_scope_aliases(project: Project) -> set[str]:
    """Derive exact aliases from a catalogue row's structured identity.

    Parent and sub-zone fields are deliberately excluded: they identify a group,
    not the row itself, and would leak one subdivision's documents into another.
    """

    raw_aliases: list[str] = [project.id, project.name]
    if " - " in project.name:
        raw_aliases.append(project.name.split(" - ", 1)[0].strip())

    return {canonical_scope_name(value) for value in raw_aliases if value.strip()}


def document_matches_project_scope(
    document: Document,
    project: Project,
    project_aliases: set[str] | None = None,
) -> bool:
    """Match an explicit project id or an exact canonical subdivision alias."""

    if document.project_id == project.id:
        return True
    if not isinstance(document.subdivision_names, list):
        return False

    aliases = project_aliases if project_aliases is not None else project_scope_aliases(project)
    document_scopes = {
        canonical_scope_name(value) for value in document.subdivision_names if isinstance(value, str) and value.strip()
    }
    return bool(document_scopes & aliases)


def document_coverage_state(
    documents: Iterable[Document],
    *,
    retrieval_project_id: str | None = None,
) -> CoverageState:
    """Summarise one project/category without reviving stale review records.

    A current, approved, completed document always wins because AI can use it. A
    current pending review remains actionable. Otherwise only the newest record
    controls the action state. This prevents an older superseded PENDING row from
    keeping the cell amber after a later upload failed, was blocked, or rejected.

    New quarantined LLM classifications carry ``classification_version`` and may
    legitimately be non-current while awaiting approval. Legacy non-current rows
    without that provenance are not presented as actionable reviews.

    ``document_matches_project_scope`` deliberately includes exact subdivision
    metadata so the Admin can find and repair legacy rows whose ``project_id`` is
    missing or wrong. Qdrant project-scoped retrieval, however, filters only its
    ``project_id`` payload. When ``retrieval_project_id`` is supplied, only a row
    carrying that exact id can make the cell ``ready``. A metadata-only LLM result
    may still be ``pending_review`` so the Admin sees the work queue; an already
    approved null/mismatched id is ``unavailable`` rather than falsely green.
    """

    related_rows = list(documents)
    if not related_rows:
        return "missing"

    retrieval_rows = (
        related_rows
        if retrieval_project_id is None
        else [row for row in related_rows if row.project_id == retrieval_project_id]
    )

    if any(
        row.is_current and row.status == DocumentStatus.COMPLETED and row.review_status == DocumentReviewStatus.APPROVED
        for row in retrieval_rows
    ):
        return "ready"

    if any(
        row.is_current and row.status == DocumentStatus.COMPLETED and row.review_status == DocumentReviewStatus.PENDING
        for row in retrieval_rows
    ):
        return "pending_review"

    latest = max(related_rows, key=lambda row: (row.created_at or datetime.min, row.id or -1))
    scope_is_actionable = bool(
        retrieval_project_id is None
        or latest.project_id == retrieval_project_id
        or latest.classification_version is not None
    )
    is_actionable_review = (
        latest.status == DocumentStatus.COMPLETED
        and latest.review_status == DocumentReviewStatus.PENDING
        and (latest.is_current or latest.classification_version is not None)
        and scope_is_actionable
    )
    if is_actionable_review:
        return "pending_review"

    return "unavailable"
