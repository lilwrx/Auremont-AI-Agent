"""Load Vinhomes Ocean Park sample data: JSON -> MySQL (projects table), images -> MinIO.

Run manually, once, whenever the demo data needs a refresh:
    python scripts/load_vinhomes_ocean_park.py
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.mysql_client import SessionLocal  # noqa: E402
from backend.models.project import Project  # noqa: E402

JSON_PATH = REPO_ROOT / "seed-data" / "vinhomes_ocean_park.json"
IMAGES_DIR = REPO_ROOT / "frontend" / "public"
IMAGE_PATTERN = re.compile(r"^003_Start-from-the-provided-parking-area-with-several-_(.+)\.jpg$")


def clean_image_key(filename: str) -> str | None:
    match = IMAGE_PATTERN.match(filename)
    if not match:
        return None
    return f"{match.group(1)}.jpg"


def upload_images() -> list[str]:
    """Ảnh nằm sẵn trong frontend/public/ — Vite/Vercel đã serve chúng ở gốc site,
    nên chỉ cần trỏ đường dẫn tương đối, không cần upload lên object storage nào."""
    urls = []
    for path in sorted(IMAGES_DIR.glob("*.jpg")):
        key = clean_image_key(path.name)
        if key is None:
            continue
        urls.append(f"/{key}")

    if not urls:
        print("[anh] không tìm thấy ảnh nào khớp pattern trong frontend/public/.")
    return urls


def load_project(gallery_urls: list[str]) -> None:
    payload = json.loads(JSON_PATH.read_text(encoding="utf-8"))
    payload["images"]["gallery"] = gallery_urls
    project = payload["project"]
    location = f"{project['location']['district']}, {project['location']['city']}"

    db = SessionLocal()
    try:
        row = db.get(Project, project["id"])
        if row is None:
            row = Project(id=project["id"])
            db.add(row)
        row.name = project["name"]
        row.location = location
        row.description = project["description"]
        row.details = payload
        db.commit()
        print(f"[mysql] upsert project '{project['id']}' OK ({len(gallery_urls)} ảnh gallery)")
    finally:
        db.close()


def main() -> None:
    gallery_urls = upload_images()
    load_project(gallery_urls)


if __name__ == "__main__":
    main()
