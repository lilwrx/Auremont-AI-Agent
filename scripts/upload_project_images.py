"""Upload toan bo anh phan khu tu project-images-source/ len MinIO.

Nguon that cua cac anh mat bang/phoi canh/layout dung trong CategoryDetailPage
(Zurich, Beverly, London, Paris, Sapphire, Senique Hanoi, Ocean View, Zenpark,
Pavilion, Palma...) — cac anh nay KHONG nam trong bang `projects` (JSON details)
nen khong di qua load_vinhomes_ocean_park.py, ma duoc code FE tro thang toi URL
MinIO dang `http://<endpoint>/project-images/<slug>/<filename>`.

Truoc day cac anh nay chi ton tai trong Docker volume MinIO tren 1 may (khong
push len git duoc), nen dong nghiep clone repo ve se thay anh vo (404). Script
nay giai quyet: chay 1 lan sau khi `docker compose up -d minio` de nap lai du
lieu tu thu muc da commit trong repo.

Chay:
    python scripts/upload_project_images.py
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend.core.config import get_settings  # noqa: E402
from backend.core.minio_client import ensure_public_read_bucket, get_minio_client, public_object_url  # noqa: E402

SOURCE_DIR = REPO_ROOT / "project-images-source"


def main() -> None:
    settings = get_settings()
    ensure_public_read_bucket(settings.minio_bucket_project_images)
    client = get_minio_client()

    if not SOURCE_DIR.exists():
        print(f"[loi] Khong thay thu muc {SOURCE_DIR} — chua co anh nguon de upload.")
        return

    uploaded = 0
    for path in sorted(SOURCE_DIR.rglob("*")):
        if not path.is_file():
            continue
        object_name = path.relative_to(SOURCE_DIR).as_posix()
        client.fput_object(settings.minio_bucket_project_images, object_name, str(path))
        print(f"[minio] uploaded {object_name}")
        uploaded += 1

    if uploaded == 0:
        print("[loi] Khong tim thay file anh nao trong project-images-source/.")
        return

    print(f"\nXong — da upload {uploaded} anh vao bucket '{settings.minio_bucket_project_images}'.")
    print(f"Vi du kiem tra: {public_object_url(settings.minio_bucket_project_images, 'the-zurich')}...")


if __name__ == "__main__":
    main()
