"""Load 7 newly crawled projects (3 Villa sub-zones + 4 Retail Shop units) into the `projects` table.

Source: seed-data/villas-shops/ (Hai Au, Ngoc Trai, Sao Bien, Shop BH9B/HA08/SB11A/SH09)
— each JSON file follows the same shape as the apartment files
(project/pricing/amenities/images/contact).

Gallery URLs come from seed-data/project_images_manifest.json — the images live on
R2/MinIO and are not checked into git.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.mysql_client import SessionLocal  # noqa: E402
from backend.models.project import Project  # noqa: E402
from scripts._gallery import gallery_by_slug  # noqa: E402

SOURCE_JSON_DIR = REPO_ROOT / "seed-data" / "villas-shops"

PROJECTS = [
    ("hai_au.json", "hai-au"),
    ("ngoc_trai.json", "ngoc-trai"),
    ("sao_bien.json", "sao-bien"),
    ("shop_thuong_mai_bh9b.json", "shop-thuong-mai-bh9b"),
    ("shop_thuong_mai_ha08.json", "shop-thuong-mai-ha08"),
    ("shop_thuong_mai_sb11a.json", "shop-thuong-mai-sb11a"),
    ("shop_thuong_mai_sh09.json", "shop-thuong-mai-sh09"),
]


def main() -> None:
    galleries = gallery_by_slug()
    db = SessionLocal()
    try:
        for json_name, slug in PROJECTS:
            json_path = SOURCE_JSON_DIR / json_name
            details = json.loads(json_path.read_text(encoding="utf-8"))

            project_info = details["project"]
            if project_info["id"] != slug:
                raise ValueError(f"Slug mismatch: config={slug} but json project.id={project_info['id']}")

            gallery = galleries.get(slug, [])
            details.setdefault("images", {})["gallery"] = gallery

            location = project_info.get("location") or {}
            location_str = ", ".join(filter(None, [location.get("district"), location.get("city")])) or None

            row = db.get(Project, slug)
            if row is None:
                row = Project(id=slug)
                db.add(row)
            short_name = project_info.get("name") or ""
            row.name = (
                f"{short_name} - Vinhomes Ocean Park"
                if short_name and "tiểu khu" in (project_info.get("full_name") or "").lower()
                else project_info.get("full_name") or short_name
            )
            row.location = location_str
            row.description = project_info.get("description")
            row.details = details

            print(f"[db] upsert {slug} — {len(gallery)} anh gallery")

        db.commit()
        print(f"\nXong — da nap {len(PROJECTS)} du an.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
