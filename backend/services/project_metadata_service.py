"""Validate and resolve project metadata proposed by the document classifier.

The LLM is allowed to choose only from the live project catalogue.  This module keeps
that boundary deterministic: an invented id never reaches the document foreign key, and
an exact subdivision name can be mapped to its catalogue row without fuzzy guessing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy.orm import Session

from backend.models.project import Project


class ProjectCatalogEntry(TypedDict):
    id: str
    name: str
    location: str | None


@dataclass(frozen=True)
class ProjectResolution:
    project_id: str | None
    requires_admin_review: bool = False
    note: str | None = None


def classification_project_catalog(db: Session) -> list[ProjectCatalogEntry]:
    """Return the complete DB catalogue, including rows hidden from the public page."""

    return [
        {"id": row.id, "name": row.name, "location": row.location}
        for row in db.query(Project).order_by(Project.name).all()
    ]


def resolve_classified_project(
    *,
    selected_project_id: str | None,
    suggested_project_id: str | None,
    subdivision_names: list[str] | None,
    catalog: list[ProjectCatalogEntry],
) -> ProjectResolution:
    """Resolve one safe project id while preserving an Admin's explicit upload choice.

    The LLM-proposed id must exist in ``catalog``.  When no project was selected during
    upload, a single exact subdivision-to-project match may fill the project id.  Conflicts
    are quarantined for Admin review instead of silently choosing one side.
    """

    catalog_ids = {entry["id"] for entry in catalog}
    suggested_is_valid = suggested_project_id in catalog_ids if suggested_project_id else False
    invalid_suggestion = bool(suggested_project_id and not suggested_is_valid)
    subdivision_matches = _matching_project_ids(subdivision_names or [], catalog)

    if selected_project_id:
        conflicts = set(subdivision_matches)
        if suggested_is_valid:
            conflicts.add(str(suggested_project_id))
        conflicts.discard(selected_project_id)
        if invalid_suggestion or conflicts:
            details = sorted(conflicts) or [str(suggested_project_id)]
            return ProjectResolution(
                project_id=selected_project_id,
                requires_admin_review=True,
                note=(
                    "Project do Admin chọn được giữ nguyên nhưng metadata LLM gợi ý phạm vi khác: "
                    + ", ".join(details)
                    + "."
                ),
            )
        return ProjectResolution(project_id=selected_project_id)

    if len(subdivision_matches) == 1:
        subdivision_project_id = next(iter(subdivision_matches))
        if suggested_is_valid and suggested_project_id != subdivision_project_id:
            return ProjectResolution(
                project_id=None,
                requires_admin_review=True,
                note=(
                    "Project LLM gợi ý mâu thuẫn với phân khu đã trích xuất: "
                    f"{suggested_project_id} / {subdivision_project_id}."
                ),
            )
        return ProjectResolution(project_id=subdivision_project_id)

    if len(subdivision_matches) > 1:
        if suggested_is_valid and suggested_project_id in subdivision_matches:
            return ProjectResolution(
                project_id=str(suggested_project_id),
                requires_admin_review=True,
                note="Tài liệu nhắc nhiều project/phân khu; cần Admin xác nhận phạm vi chính.",
            )
        return ProjectResolution(
            project_id=None,
            requires_admin_review=True,
            note="Tài liệu khớp nhiều project/phân khu; không tự gán một project duy nhất.",
        )

    if invalid_suggestion:
        return ProjectResolution(
            project_id=None,
            requires_admin_review=True,
            note=f"LLM trả project_id không tồn tại trong catalogue: {suggested_project_id}.",
        )

    return ProjectResolution(project_id=str(suggested_project_id) if suggested_is_valid else None)


def _matching_project_ids(
    subdivision_names: list[str],
    catalog: list[ProjectCatalogEntry],
) -> set[str]:
    aliases_by_id = {entry["id"]: _project_aliases(entry) for entry in catalog}
    matches: set[str] = set()
    for subdivision_name in subdivision_names:
        key = _metadata_key(subdivision_name)
        if not key:
            continue
        matches.update(project_id for project_id, aliases in aliases_by_id.items() if key in aliases)
    return matches


def _project_aliases(entry: ProjectCatalogEntry) -> set[str]:
    name = entry["name"]
    aliases = {_metadata_key(entry["id"]), _metadata_key(name)}
    if " - " in name:
        aliases.add(_metadata_key(name.split(" - ", 1)[0]))
    return {alias for alias in aliases if alias}


def _metadata_key(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", ascii_value).casefold().split())
