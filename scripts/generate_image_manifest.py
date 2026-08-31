"""Sinh lai seed-data/project_images_manifest.json tu thu muc anh nguon.

Anh du an KHONG nam trong git (xem .gitignore) — chung song tren S3/CDN va duoc
loader tai ve MinIO luc backend khoi dong. Manifest nay la danh sach duong dan de
loader biet phai tai gi, va de nguoi maintain biet phai upload gi len CDN.

Chay lai moi khi them/bot anh trong project-images-source/:
    python scripts/generate_image_manifest.py
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = REPO_ROOT / "project-images-source"
MANIFEST_PATH = REPO_ROOT / "seed-data" / "project_images_manifest.json"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def main() -> None:
    if not SOURCE_DIR.exists():
        print(f"[loi] Khong thay {SOURCE_DIR}. Tai anh tu CDN ve truoc khi sinh manifest.")
        sys.exit(1)

    paths = sorted(
        p.relative_to(SOURCE_DIR).as_posix()
        for p in SOURCE_DIR.rglob("*")
        if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
    )
    if not paths:
        print(f"[loi] Khong tim thay anh nao trong {SOURCE_DIR}.")
        sys.exit(1)

    total = sum((SOURCE_DIR / p).stat().st_size for p in paths)
    payload = {
        "_comment": (
            "Danh sach anh du an. Loader tai <PROJECT_IMAGES_BASE_URL>/<path> vao MinIO "
            "luc khoi dong. Sinh boi scripts/generate_image_manifest.py"
        ),
        "count": len(paths),
        "total_bytes": total,
        "images": paths,
    }
    MANIFEST_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[ok] Ghi {MANIFEST_PATH.relative_to(REPO_ROOT)} — {len(paths)} anh, {total / 1024 / 1024:.1f} MB.")


if __name__ == "__main__":
    main()
