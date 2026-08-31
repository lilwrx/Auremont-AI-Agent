from types import SimpleNamespace

from backend.core import bootstrap_data
from scripts._gallery import gallery_by_slug


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.commits = 0

    def query(self, _model):
        return _Query(self.rows)

    def commit(self):
        self.commits += 1

    def close(self):
        pass


def test_one_populated_project_is_not_mistaken_for_a_complete_catalogue(monkeypatch):
    rows = [SimpleNamespace(id="parent", details={"project": {"id": "parent"}})]
    monkeypatch.setattr(bootstrap_data, "SessionLocal", lambda: _Session(rows))
    monkeypatch.setattr(bootstrap_data, "_expected_catalogue_ids", lambda: {"parent", "child"})

    assert bootstrap_data._catalogue_is_loaded() is False


def test_catalogue_is_complete_only_when_every_seed_record_is_present(monkeypatch):
    rows = [
        SimpleNamespace(id="parent", details={"project": {"id": "parent"}}),
        SimpleNamespace(id="child", details={"project": {"id": "child"}}),
    ]
    monkeypatch.setattr(bootstrap_data, "SessionLocal", lambda: _Session(rows))
    monkeypatch.setattr(bootstrap_data, "_expected_catalogue_ids", lambda: {"parent", "child"})

    assert bootstrap_data._catalogue_is_loaded() is True


def test_existing_catalogue_still_syncs_missing_project_images(monkeypatch):
    settings = SimpleNamespace(
        auto_load_demo_data=True,
        project_images_archive_url="https://cdn.example.test/project-images.tar.gz",
        project_images_base_url="https://cdn.example.test/project-images",
    )
    downloaded: list[str] = []
    gallery_syncs: list[str] = []
    monkeypatch.setattr(bootstrap_data, "get_settings", lambda: settings)
    monkeypatch.setattr(bootstrap_data, "_catalogue_is_loaded", lambda: True)
    monkeypatch.setattr(
        bootstrap_data,
        "_sync_catalogue_galleries",
        lambda: gallery_syncs.append("sync") or 0,
    )
    monkeypatch.setattr(
        bootstrap_data,
        "_download_archive_to_minio",
        lambda url: downloaded.append(url) or 2,
    )

    bootstrap_data.load_demo_data()

    assert downloaded == [settings.project_images_archive_url]
    assert gallery_syncs == ["sync"]


def test_catalogue_gallery_sync_preserves_other_project_details(monkeypatch):
    old_gallery = ["https://cdn.example.test/old.jpg"]
    new_gallery = ["https://cdn.example.test/new.jpg"]
    project = SimpleNamespace(
        id="the-beverly",
        details={"images": {"gallery": old_gallery, "logo": "logo.svg"}, "pricing": {"min": 1.81}},
    )
    session = _Session([project])
    monkeypatch.setattr(bootstrap_data, "SessionLocal", lambda: session)
    monkeypatch.setattr("scripts._gallery.gallery_by_slug", lambda: {"the-beverly": new_gallery})

    assert bootstrap_data._sync_catalogue_galleries() == 1
    assert session.commits == 1
    assert project.details == {
        "images": {"gallery": new_gallery, "logo": "logo.svg"},
        "pricing": {"min": 1.81},
    }


def test_beverly_manifest_exposes_all_room_layouts():
    filenames = {url.rsplit("/", 1)[-1] for url in gallery_by_slug()["the-beverly"]}

    assert {
        "mat-bang-can-ho-1pn-beverly-vinhomes-ocean-park.jpg",
        "mat-bang-can-ho-2pn-beverly-vinhomes-ocean-park.jpg",
        "mat-bang-can-ho-2pn1-beverly-vinhomes-ocean-park.jpg",
        "mat-bang-can-ho-3pn-beverly-vinhomes-ocean-park.jpg",
    } <= filenames
