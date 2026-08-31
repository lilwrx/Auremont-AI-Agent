import json
from pathlib import Path
from types import SimpleNamespace

from backend.services import catalog_context_service


class _Project:
    id = "the-pavilion"
    name = "The Pavilion"
    details = {
        "tower_details": {
            "P4": {
                "subdivision": "The Pavilion",
                "parent_sub_zone": "The Ocean View",
                "scale": "30 tầng nổi và 2 tầng hầm",
                "floor_use": ["Tầng 3–13 và 15–30: căn hộ", "Tầng 14: phòng lánh nạn"],
                "road_adjacency": "Kề đường nội khu rộng 17 m",
            }
        }
    }


class _Query:
    def all(self):
        return [_Project()]


class _Db:
    def get(self, _model, project_id):
        return _Project() if project_id == "the-pavilion" else None

    def query(self, _model):
        return _Query()


def test_exact_tower_context_overrides_cluster_level_range():
    context = catalog_context_service.tower_context(
        _Db(), "the-pavilion", "Tòa P4 thuộc phân khu nào, bao nhiêu tầng và tiếp giáp đường nào?"
    )

    assert "Tòa: P4" in context
    assert "Phân khu: The Pavilion" in context
    assert "Đại phân khu: The Ocean View" in context
    assert "30 tầng nổi và 2 tầng hầm" in context
    assert "đường nội khu rộng 17 m" in context
    assert "Công năng tầng" not in context
    assert "Ranh giới vị trí" not in context
    assert "bắt buộc dùng hồ sơ tòa" in context
    assert "không bổ sung một thuộc tính riêng của tòa" in context


def test_does_not_add_tower_context_when_query_does_not_name_one():
    assert catalog_context_service.tower_context(_Db(), "the-pavilion", "The Pavilion có gì?") == ""


def test_can_resolve_unique_tower_without_project_scope():
    context = catalog_context_service.tower_context(_Db(), None, "Cho tôi thông tin tòa P4")

    assert "Tòa: P4" in context


def test_tower_profile_query_is_exclusive_but_mixed_policy_query_is_not():
    assert catalog_context_service.is_tower_profile_query(
        "Tòa P4 thuộc phân khu nào, bao nhiêu tầng và tiếp giáp đường nào?"
    )
    assert not catalog_context_service.is_tower_profile_query(
        "Tòa P4 có bao nhiêu tầng và chính sách thanh toán thế nào?"
    )


def test_every_named_tower_in_every_apartment_subdivision_is_resolvable():
    """Coverage guard: the resolver must not silently become a P4-only feature."""
    root = Path(__file__).resolve().parents[2]
    projects = {}
    expected_towers = 0
    for path in (root / "seed-data" / "apartments").glob("*.json"):
        details = json.loads(path.read_text(encoding="utf-8"))
        towers = ((details.get("project") or {}).get("overview") or {}).get("towers") or []
        if not isinstance(towers, list):
            continue
        project_id = details["project"]["id"]
        projects[project_id] = SimpleNamespace(
            id=project_id,
            name=details["project"]["name"],
            details=details,
        )
        for tower in towers:
            expected_towers += 1
            result = catalog_context_service.resolve_tower_context(
                _CatalogueDb(projects), project_id, f"Tòa {tower} thuộc phân khu nào?"
            )
            assert f"Tòa: {tower}" in result.text
            assert f"Phân khu: {details['project']['name']}" in result.text
            assert result.complete is True

    assert expected_towers >= 50


def test_missing_tower_detail_never_promotes_the_subdivision_floor_range():
    details = {
        "project": {
            "name": "The Beverly",
            "sub_zone": "The Metropolitan",
            "overview": {"towers": ["BE2"], "floors": "30–35 tầng"},
        }
    }
    project = SimpleNamespace(id="the-beverly", name="The Beverly", details=details)

    result = catalog_context_service.resolve_tower_context(
        _CatalogueDb({project.id: project}), project.id, "Tòa BE2 có bao nhiêu tầng?"
    )

    assert result.complete is False
    assert "30–35" not in result.text
    assert "các thuộc tính cấp tòa còn thiếu" in result.text


def test_project_profile_exposes_grounded_location_price_policy_and_amenities():
    root = Path(__file__).resolve().parents[2]
    details = json.loads((root / "seed-data" / "apartments" / "the_beverly.json").read_text(encoding="utf-8"))
    project = SimpleNamespace(id="the-beverly", name="The Beverly", details=details)
    db = _CatalogueDb({project.id: project})

    context = catalog_context_service.project_profile_context(
        db,
        project.id,
        "Dự án ở đâu, chủ đầu tư là ai, giá căn Studio, chính sách vay và tiện ích có gì?",
    )

    assert "Mitsubishi Corporation và Vingroup" in context
    assert "Vinhomes Ocean Park, Quận Gia Lâm, Hà Nội" in context
    assert "Studio: diện tích 28–36 m²; giá tham khảo 1.8–2.1 tỷ đồng" in context
    assert "Hỗ trợ vay 70%" in context
    assert "Bể bơi Santa Monica" in context
    assert "không xác nhận căn đang còn" in context
    assert "cần xác nhận bản chính sách hiện hành" in context


def test_project_profile_does_not_bloat_an_unrelated_conversation_turn():
    root = Path(__file__).resolve().parents[2]
    details = json.loads((root / "seed-data" / "apartments" / "the_beverly.json").read_text(encoding="utf-8"))
    project = SimpleNamespace(id="the-beverly", name="The Beverly", details=details)

    context = catalog_context_service.project_profile_context(
        _CatalogueDb({project.id: project}), project.id, "Xin chào"
    )

    assert context == ""


def test_travel_question_gets_known_location_but_not_an_invented_travel_time():
    root = Path(__file__).resolve().parents[2]
    details = json.loads((root / "seed-data" / "apartments" / "the_beverly.json").read_text(encoding="utf-8"))
    project = SimpleNamespace(id="the-beverly", name="The Beverly", details=details)

    context = catalog_context_service.project_profile_context(
        _CatalogueDb({project.id: project}), project.id, "Di chuyển đến trung tâm mất bao lâu?"
    )

    assert "Vinhomes Ocean Park, Quận Gia Lâm, Hà Nội" in context
    assert "Không suy ra thời gian di chuyển" in context


class _CatalogueDb:
    def __init__(self, projects):
        self.projects = projects

    def get(self, _model, project_id):
        return self.projects.get(project_id)

    def query(self, _model):
        return _CatalogueQuery(list(self.projects.values()))


class _CatalogueQuery:
    def __init__(self, projects):
        self.projects = projects

    def all(self):
        return self.projects
