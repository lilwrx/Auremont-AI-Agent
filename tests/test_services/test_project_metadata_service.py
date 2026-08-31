from backend.services.project_metadata_service import resolve_classified_project

CATALOG = [
    {"id": "hai-au", "name": "Hải Âu - Vinhomes Ocean Park", "location": "Hà Nội"},
    {"id": "the-beverly", "name": "The Beverly - Vinhomes Ocean Park", "location": "Hà Nội"},
    {"id": "vinhomes-ocean-park", "name": "Vinhomes Ocean Park", "location": "Hà Nội"},
]


def test_exact_subdivision_alias_fills_missing_project_id():
    result = resolve_classified_project(
        selected_project_id=None,
        suggested_project_id=None,
        subdivision_names=["Hai Au"],
        catalog=CATALOG,
    )

    assert result.project_id == "hai-au"
    assert result.requires_admin_review is False


def test_unknown_llm_project_id_is_never_persisted():
    result = resolve_classified_project(
        selected_project_id=None,
        suggested_project_id="project-hallucinated",
        subdivision_names=None,
        catalog=CATALOG,
    )

    assert result.project_id is None
    assert result.requires_admin_review is True


def test_explicit_admin_project_wins_but_a_conflict_requires_review():
    result = resolve_classified_project(
        selected_project_id="vinhomes-ocean-park",
        suggested_project_id="the-beverly",
        subdivision_names=["The Beverly"],
        catalog=CATALOG,
    )

    assert result.project_id == "vinhomes-ocean-park"
    assert result.requires_admin_review is True


def test_conflicting_project_and_subdivision_are_quarantined():
    result = resolve_classified_project(
        selected_project_id=None,
        suggested_project_id="vinhomes-ocean-park",
        subdivision_names=["The Beverly"],
        catalog=CATALOG,
    )

    assert result.project_id is None
    assert result.requires_admin_review is True
