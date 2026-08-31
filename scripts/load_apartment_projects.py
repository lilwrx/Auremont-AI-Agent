"""Load the 9 apartment sub-projects into the `projects` table.

Source: seed-data/apartments/ — same JSON shape as the villa/shop files
(project/pricing/amenities/images/contact).
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.mysql_client import SessionLocal  # noqa: E402
from backend.models.project import Project  # noqa: E402
from scripts._gallery import gallery_by_slug  # noqa: E402

SOURCE_JSON_DIR = REPO_ROOT / "seed-data" / "apartments"

PROJECTS = [
    ("the_palma.json", "the-palma"),
    ("the_sapphire.json", "the-sapphire"),
    ("the_zurich.json", "the-zurich"),
    ("the_beverly.json", "the-beverly"),
    ("the_london.json", "the-london"),
    ("the_paris.json", "the-paris"),
    ("the_zenpark.json", "the-zenpark"),
    ("the_pavilion.json", "the-pavilion"),
    ("the_senique_hanoi.json", "the-senique-hanoi"),
]


def main() -> None:
    galleries = gallery_by_slug()
    db = SessionLocal()
    try:
        for json_name, slug in PROJECTS:
            details = json.loads((SOURCE_JSON_DIR / json_name).read_text(encoding="utf-8"))

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
            row.name = project_info.get("full_name") or project_info.get("name") or slug
            row.location = location_str
            row.description = project_info.get("description")
            row.details = details

            print(f"[db] upsert {slug} - {len(gallery)} anh gallery")

        db.commit()
        print(f"\nXong - da nap {len(PROJECTS)} du an chung cu.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
