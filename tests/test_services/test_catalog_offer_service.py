import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.services import (
    agent_pipeline,
    answer_images_service,
    catalog_offer_service,
    inventory_service,
    search_criteria,
)

ROOT = Path(__file__).resolve().parents[2]


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return list(self.rows)


class _Db:
    def __init__(self, rows):
        self.rows = rows

    def query(self, _model):
        return _Query(self.rows)


@pytest.fixture(scope="module")
def catalogue_db():
    paths = [
        ROOT / "seed-data" / "vinhomes_ocean_park.json",
        *(ROOT / "seed-data" / "apartments").glob("*.json"),
        *(ROOT / "seed-data" / "villas-shops").glob("*.json"),
    ]
    rows = []
    for path in paths:
        details = json.loads(path.read_text(encoding="utf-8"))
        info = details["project"]
        rows.append(
            SimpleNamespace(
                id=info["id"],
                name=info.get("full_name") or info.get("name") or info["id"],
                details=details,
            )
        )
    return _Db(rows)


def _criteria(query: str) -> search_criteria.SearchCriteria:
    return search_criteria.merge_criteria(search_criteria.SearchCriteria(), search_criteria.parse_criteria(query))


def test_every_seeded_project_and_pricing_tier_is_searchable(catalogue_db):
    """Every real sub-zone's pricing tiers are searchable in a broad, unscoped query —
    except the umbrella "Vinhomes Ocean Park" catalogue entry, which mixes "Chung cư"
    together with "Biệt thự"/"Shophouse" (no real sub-zone does that) and would otherwise
    surface as a peer "phân khu" option next to The Beverly/The Zurich. Ngọc Trai/Sao Biển
    legitimately mix two non-apartment categories (villas plus a few shophouse units in the
    same sub-zone) and must stay searchable — only the umbrella's own combination is
    excluded, see `search_offers`."""
    umbrella_id = "vinhomes-ocean-park"
    expected_ids = {row.id for row in catalogue_db.rows} - {umbrella_id}
    expected = sum(len(row.details.get("pricing") or []) for row in catalogue_db.rows if row.id != umbrella_id)

    offers = catalog_offer_service.search_offers(
        catalogue_db, "tư vấn các loại bất động sản", criteria=search_criteria.SearchCriteria(), limit=200
    )

    assert len(offers) == expected == 73
    assert {offer.project_id for offer in offers} == expected_ids


def test_umbrella_project_is_still_searchable_when_explicitly_scoped(catalogue_db):
    """A question that names "Vinhomes Ocean Park" directly still gets its own tiers back —
    the exclusion above only applies to a broad, unscoped search."""
    offers = catalog_offer_service.search_offers(
        catalogue_db,
        "vinhomes ocean park",
        project_ids=["vinhomes-ocean-park"],
        criteria=search_criteria.SearchCriteria(),
        limit=200,
    )

    assert offers
    assert {offer.project_id for offer in offers} == {"vinhomes-ocean-park"}


@pytest.mark.parametrize(
    "query",
    [
        "studio",
        "1PN",
        "1PN+1",
        "2 phòng ngủ",
        "2PN+",
        "3PN",
        "3PN+1",
        "4PN",
        "duplex",
        "penthouse",
        "biệt thự",
        "biệt thự đơn lập",
        "song lập",
        "liền kề",
        "shophouse",
    ],
)
def test_every_catalogue_product_family_can_be_asked_in_customer_language(catalogue_db, query):
    criteria = _criteria(query)
    wanted = criteria.get(search_criteria.FIELD_UNIT_TYPES)
    assert wanted is not None

    offers = catalog_offer_service.search_offers(catalogue_db, query, criteria=criteria, limit=200)

    assert offers
    for offer in offers:
        actual = inventory_service._extract_unit_types(f"{offer.unit_type} {offer.category}")
        assert any(
            inventory_service.unit_type_matches(candidate, requested)
            for candidate in actual
            for requested in wanted.value
        )


def test_budget_search_uses_the_named_projects_price_tiers(catalogue_db):
    offers = catalog_offer_service.search_offers(
        catalogue_db,
        "The Pavilion có loại căn nào dưới 3 tỷ?",
        project_ids=["the-pavilion"],
        criteria=_criteria("dưới 3 tỷ"),
    )

    assert {offer.project_id for offer in offers} == {"the-pavilion"}
    assert {offer.unit_type for offer in offers} == {"Studio", "1 ngủ", "1 ngủ + 1", "2 ngủ"}
    assert "3 ngủ" not in {offer.unit_type for offer in offers}
    assert "không phải xác nhận căn đang còn" in catalog_offer_service.format_offers(offers)


def test_parent_scope_finds_child_apartments_for_typographic_area_request(catalogue_db):
    query = (
        "Toi can can 2PN khoang 60–70m2, uu tien huong Dong Nam va view dep. "
        "Trong cac phan khu Ocean Park 1 co lua chon nao?"
    )
    criteria = _criteria(query)
    offers = catalog_offer_service.search_offers(
        catalogue_db,
        query,
        project_ids=["vinhomes-ocean-park"],
        criteria=criteria,
        limit=200,
    )

    assert criteria.get(search_criteria.FIELD_AREA).value == (60.0, 70.0)
    assert {offer.project_id for offer in offers} >= {"the-zenpark", "the-sapphire", "the-paris"}
    assert all("2" in offer.unit_type for offer in offers)
    assert [offer.project_id for offer in offers[:3]] == ["the-sapphire", "the-paris", "the-zenpark"]
    context = catalog_offer_service.format_offers(offers, criteria)
    assert "ĐỘ PHỦ KHỚP MỘT PHẦN" in context
    assert "không được kết luận không có lựa chọn" in context
    assert "view dep" in context


def test_unknown_villa_price_is_kept_and_labelled_instead_of_dropped(catalogue_db):
    offers = catalog_offer_service.search_offers(
        catalogue_db,
        "biệt thự Hải Âu dưới 20 tỷ",
        project_ids=["hai-au"],
        criteria=_criteria("biệt thự dưới 20 tỷ"),
    )

    assert len(offers) == 3
    assert all(offer.price_min is None for offer in offers)
    assert "Liên hệ / Tải bảng giá gốc" in catalog_offer_service.format_offers(offers)


def test_project_scope_resolves_project_subzone_and_unique_tower(catalogue_db):
    assert answer_images_service.resolve_project_ids(catalogue_db, "giá The Pavilion") == ["the-pavilion"]
    assert answer_images_service.resolve_project_ids(catalogue_db, "thông tin tòa P4") == ["the-pavilion"]

    ocean_view_ids = answer_images_service.resolve_project_ids(catalogue_db, "các căn ở The Ocean View")
    assert ocean_view_ids == ["the-pavilion"]


def test_every_catalogue_subdivision_short_name_resolves(catalogue_db):
    for row in catalogue_db.rows:
        short_name = row.details["project"].get("name")
        assert short_name
        assert row.id in answer_images_service.resolve_project_ids(catalogue_db, f"cho tôi thông tin {short_name}")


def test_negative_project_reference_is_not_returned_as_positive_scope(catalogue_db):
    references = answer_images_service.resolve_project_references(
        catalogue_db, "ngoài Zenpark thì tôi có thể cân nhắc căn nào khác"
    )

    assert references.included_ids == ()
    assert references.excluded_ids == ("the-zenpark",)
    assert answer_images_service.resolve_project_id(catalogue_db, "trừ The Zenpark") is None


@pytest.mark.parametrize(
    "query",
    [
        "Ngoài ra, Zenpark cũng có lựa chọn nào?",
        "Có căn nào khác ở Zenpark không?",
    ],
)
def test_non_negative_connectors_keep_project_in_positive_scope(catalogue_db, query):
    references = answer_images_service.resolve_project_references(catalogue_db, query)

    assert references.included_ids == ("the-zenpark",)
    assert references.excluded_ids == ()


def test_parent_scope_includes_children_but_excludes_rejected_subdivision(catalogue_db):
    offers = catalog_offer_service.search_offers(
        catalogue_db,
        "ngoài Zenpark thì có căn nào dưới 4 tỷ",
        project_ids=["vinhomes-ocean-park"],
        excluded_project_ids=["the-zenpark"],
        criteria=_criteria("dưới 4 tỷ"),
        limit=200,
    )

    project_ids = {offer.project_id for offer in offers}
    assert "the-zenpark" not in project_ids
    assert "vinhomes-ocean-park" in project_ids
    assert len(project_ids) > 2


def test_follow_up_outside_subdivision_keeps_parent_history_scope(catalogue_db):
    scope = agent_pipeline._scope_resolve(
        {
            "query": "ngoài Zenpark thì tôi có thể cân nhắc căn nào khác",
            "db": catalogue_db,
            "project_id": None,
            "history": [
                {
                    "sender": "customer",
                    "content": "Ngân sách 4 tỷ, trong Ocean Park 1 có những căn nào?",
                }
            ],
        }
    )

    assert scope["resolved_project_ids"] == ["vinhomes-ocean-park"]
    assert scope["excluded_project_ids"] == ["the-zenpark"]
    result = agent_pipeline._catalog_search_result(
        {
            "query": "ngoài Zenpark thì tôi có thể cân nhắc căn nào khác",
            "db": catalogue_db,
            "needs_inventory": True,
            **scope,
        },
        _criteria("dưới 4 tỷ"),
    )
    assert result["catalog_offers"]
    assert all(offer.project_id != "the-zenpark" for offer in result["catalog_offers"])
