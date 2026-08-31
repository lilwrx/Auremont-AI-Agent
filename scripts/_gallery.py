"""Gallery URLs derived from the image manifest.

Original images live on a public R2 bucket and are never checked into git, so a
fresh clone has the manifest but no local image directory to scan.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.config import get_settings  # noqa: E402

MANIFEST_PATH = REPO_ROOT / "seed-data" / "project_images_manifest.json"


def gallery_by_slug() -> dict[str, list[str]]:
    """One URL per photo, preferring the copy filed under a category folder.

    237 of the manifest's entries are the same photo listed twice: once at
    `<slug>/<file>` and again at `<slug>/<category>/<file>`, where category is one of
    tien_ich / mat_bang / hinh_anh_thuc_te. Emitting both puts every such photo in the
    gallery twice, and the customer sees it twice in the strip under an answer.

    The categorised path is the one kept, because that folder is the only place the
    photo's topic is recorded — filenames like `san-the-thao-the-zenpark.jpg` or
    `vuon-nhat-the-zenpark.jpg` never say "tien ich" themselves, so dropping the folder
    would leave answer_images_service with nothing to match an amenity question on.
    """
    if not MANIFEST_PATH.exists():
        return {}

    base_url = get_settings().project_images_base_url.rstrip("/")
    grouped: dict[str, dict[str, str]] = {}
    for key in json.loads(MANIFEST_PATH.read_text(encoding="utf-8")).get("images", []):
        slug, _, rest = key.partition("/")
        if not rest:
            continue
        filename = rest.rsplit("/", 1)[-1]
        by_filename = grouped.setdefault(slug, {})
        if filename in by_filename and "/" not in rest:
            continue
        by_filename[filename] = f"{base_url}/{key}"
    return {slug: list(by_filename.values()) for slug, by_filename in grouped.items()}
