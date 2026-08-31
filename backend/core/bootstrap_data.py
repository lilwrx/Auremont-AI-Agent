"""Nap du lieu demo (anh -> MinIO, catalogue -> MySQL) ngay khi backend khoi dong.

Truoc day phai chay tay 3 script sau khi `docker compose up`; ai bo qua buoc do se
thay trang Tra cuu trong tron va toan bo anh vo — khong co tin hieu nao chi ra
nguyen nhan. Muc tieu cua module nay: clone repo, `docker compose up`, xong.

Anh du an KHONG nam trong git (~58 MB). Chung song tren S3/R2 va duoc tai
ve MinIO o day, theo danh sach trong seed-data/project_images_manifest.json.

Co hai nguon:

* `PROJECT_IMAGES_BASE_URL` — thu muc cong khai (R2 public URL, S3 public, CDN),
  ghep base + duong dan trong manifest. Doc an danh: khong can credentials, nen
  khong phai phat tan API key cho ca team chi de xem anh.
* `PROJECT_IMAGES_ARCHIVE_URL` — mot file .tar.gz duy nhat; mot request thay vi ~180.

Ba tinh chat bat buoc:

* **Idempotent** — bo qua anh da co tren MinIO va chi bo qua buoc nap catalogue khi
  catalogue da co du lieu. Anh van duoc doi chieu moi lan khoi dong de mot MinIO cu
  khong bi ket vinh vien khi manifest co them file moi.
* **Khong bao gio chan khoi dong** — nguon loi, MinIO chua san sang hay thieu bien
  moi truong chi lam hong du lieu demo, khong phai ly do de ca API sap.
* **Khong tu y ra Internet khi chua duoc cau hinh** — thieu ca hai bien thi bo qua
  im lang kem mot dong log, khong doan mo URL.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import BinaryIO, cast
from urllib.parse import urljoin

from backend.core.config import get_settings
from backend.core.mysql_client import SessionLocal
from backend.models.project import Project

logger = logging.getLogger(__name__)

_DOWNLOAD_WORKERS = 8
_DOWNLOAD_TIMEOUT_SECONDS = 30
_ARCHIVE_TIMEOUT_SECONDS = 300


def _catalogue_is_loaded() -> bool:
    """True only when every catalogue record shipped in seed-data is loaded.

    One populated project is not a complete catalogue. Treating it as complete leaves a
    partially seeded deployment stuck forever because every later restart skips all
    loaders. Expected IDs are discovered from data files, not duplicated in code.
    """
    db = SessionLocal()
    try:
        loaded_ids = {row.id for row in db.query(Project).all() if row.details}
        expected_ids = _expected_catalogue_ids()
        return bool(expected_ids) and expected_ids <= loaded_ids
    finally:
        db.close()


def _expected_catalogue_ids() -> set[str]:
    root = Path(__file__).resolve().parents[2] / "seed-data"
    paths = [root / "vinhomes_ocean_park.json"]
    paths.extend((root / "apartments").glob("*.json"))
    paths.extend((root / "villas-shops").glob("*.json"))

    ids: set[str] = set()
    for path in paths:
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            project_id = ((payload.get("project") or {}).get("id") or "").strip()
            if project_id:
                ids.add(project_id)
        except (OSError, ValueError, TypeError):
            logger.warning("Khong doc duoc catalogue seed %s.", path, exc_info=True)
    return ids


def _read_manifest() -> list[str]:
    path = Path(__file__).resolve().parents[2] / "seed-data" / "project_images_manifest.json"
    if not path.exists():
        logger.warning("Khong thay manifest anh tai %s — bo qua buoc tai anh.", path)
        return []
    return json.loads(path.read_text(encoding="utf-8")).get("images", [])


def _download_archive_to_minio(archive_url: str) -> int:
    """Tai mot .tar.gz chua toan bo anh roi nap vao MinIO. Tra ve so anh da nap moi."""
    import tarfile
    import tempfile

    import httpx
    from minio.error import S3Error

    from backend.core.minio_client import ensure_public_read_bucket, get_minio_client

    settings = get_settings()
    bucket = settings.minio_bucket_project_images
    ensure_public_read_bucket(bucket)
    client = get_minio_client()

    existing = {o.object_name for o in client.list_objects(bucket, recursive=True)}
    wanted = set(_read_manifest())
    if wanted and wanted <= existing:
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        archive_path = f"{tmp}/images.tar.gz"
        with httpx.stream("GET", archive_url, timeout=_ARCHIVE_TIMEOUT_SECONDS, follow_redirects=True) as resp:
            resp.raise_for_status()
            with open(archive_path, "wb") as fh:
                for chunk in resp.iter_bytes(chunk_size=1024 * 1024):
                    fh.write(chunk)

        loaded = 0
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getmembers():
                if not member.isfile():
                    continue
                name = member.name.lstrip("./")
                if name.startswith("/") or ".." in name.split("/"):
                    logger.warning("Bo qua duong dan bat thuong trong archive: %r", member.name)
                    continue
                if name in existing:
                    continue
                member_stream = tar.extractfile(member)
                if member_stream is None:
                    continue
                try:
                    client.put_object(bucket, name, cast(BinaryIO, member_stream), length=member.size)
                    loaded += 1
                except S3Error:
                    logger.warning("Nap anh '%s' vao MinIO that bai.", name, exc_info=True)
    return loaded


def _download_images_to_minio(base_url: str) -> int:
    """Tai anh tu CDN vao MinIO. Tra ve so anh da tai moi."""
    import httpx
    from minio.error import S3Error

    from backend.core.minio_client import ensure_public_read_bucket, get_minio_client

    settings = get_settings()
    bucket = settings.minio_bucket_project_images
    ensure_public_read_bucket(bucket)
    client = get_minio_client()

    images = _read_manifest()
    if not images:
        return 0

    def fetch_one(object_name: str) -> bool:
        try:
            try:
                client.stat_object(bucket, object_name)
                return False
            except S3Error:
                pass

            url = urljoin(base_url.rstrip("/") + "/", object_name)
            resp = httpx.get(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True)
            resp.raise_for_status()
            client.put_object(
                bucket,
                object_name,
                BytesIO(resp.content),
                length=len(resp.content),
                content_type=resp.headers.get("content-type", "image/jpeg"),
            )
            return True
        except Exception:
            logger.warning("Tai anh '%s' that bai.", object_name, exc_info=True)
            return False

    with ThreadPoolExecutor(max_workers=_DOWNLOAD_WORKERS) as pool:
        return sum(pool.map(fetch_one, images))


def _sync_project_images() -> None:
    """Doi chieu manifest va nap rieng cac anh MinIO con thieu.

    Anh va catalogue co vong doi khac nhau: MySQL da day du khong co nghia bucket
    MinIO da day du (volume moi, manifest moi, hoac lan tai R2 truoc bi ngat). Vi vay
    ham nay phai chay truoc phep kiem tra catalogue trong moi lan bootstrap.
    """
    settings = get_settings()
    archive_url = settings.project_images_archive_url
    base_url = settings.project_images_base_url

    if archive_url:
        try:
            count = _download_archive_to_minio(archive_url)
            logger.info("Nap anh du an tu archive xong — %d anh moi.", count)
        except Exception:
            logger.error("Nap anh du an tu archive that bai — trang Tra cuu se thieu anh.", exc_info=True)
    elif base_url:
        try:
            count = _download_images_to_minio(base_url)
            logger.info("Tai anh du an vao MinIO xong — %d anh moi.", count)
        except Exception:
            logger.error("Tai anh du an that bai — trang Tra cuu se thieu anh.", exc_info=True)
    else:
        logger.warning(
            "Chua dat PROJECT_IMAGES_BASE_URL hay PROJECT_IMAGES_ARCHIVE_URL — bo qua "
            "buoc tai anh, catalogue se hien thi khong co anh."
        )


def _sync_catalogue_galleries() -> int:
    """Refresh gallery metadata without overwriting the rest of a seeded catalogue."""
    from scripts._gallery import gallery_by_slug

    galleries = gallery_by_slug()
    db = SessionLocal()
    updated = 0
    try:
        for project in db.query(Project).all():
            gallery = galleries.get(project.id)
            if gallery is None:
                continue

            details = dict(project.details or {})
            images = dict(details.get("images") or {})
            if images.get("gallery") == gallery:
                continue

            images["gallery"] = gallery
            details["images"] = images
            project.details = details
            updated += 1

        if updated:
            db.commit()
        return updated
    finally:
        db.close()


def load_demo_data() -> None:
    settings = get_settings()
    if not settings.auto_load_demo_data:
        return

    _sync_project_images()

    try:
        refreshed = _sync_catalogue_galleries()
        if refreshed:
            logger.info("Cap nhat gallery tu manifest cho %d du an.", refreshed)
    except Exception:
        logger.warning("Khong dong bo duoc gallery catalogue tu manifest.", exc_info=True)

    try:
        if _catalogue_is_loaded():
            logger.info("Catalogue da co du lieu — bo qua buoc nap catalogue.")
            return
    except Exception:
        logger.warning("Khong kiem tra duoc trang thai catalogue.", exc_info=True)

    from scripts.load_apartment_projects import main as load_apartments
    from scripts.load_villa_shop_projects import main as load_villas_and_shops
    from scripts.load_vinhomes_ocean_park import main as load_ocean_park

    for label, loader in (
        ("vinhomes-ocean-park", load_ocean_park),
        ("villas-shops", load_villas_and_shops),
        ("apartments", load_apartments),
    ):
        try:
            loader()
            logger.info("Nap catalogue '%s' thanh cong.", label)
        except Exception:
            logger.error("Nap catalogue '%s' that bai — trang Tra cuu se thieu du lieu.", label, exc_info=True)
