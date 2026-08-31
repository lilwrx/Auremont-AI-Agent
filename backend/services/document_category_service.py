"""Compatibility helpers for primary and multi-label document categories."""

from typing import Any

from backend.core.enums import DocumentCategory


def document_categories(document: Any) -> list[str]:
    """Return stable, deduplicated labels while supporting pre-migration rows."""

    primary = str(getattr(document, "category", None) or DocumentCategory.OTHER)
    raw = getattr(document, "categories", None)
    values = [primary, *(raw if isinstance(raw, list) else [])]
    result: list[str] = []
    for value in values:
        category = str(value).strip()
        if category and category not in result:
            result.append(category)
    return result or [DocumentCategory.OTHER.value]


def document_has_category(document: Any, category: str | DocumentCategory) -> bool:
    return str(category) in document_categories(document)


def documents_share_category(left: Any, right: Any) -> bool:
    return bool(set(document_categories(left)) & set(document_categories(right)))
