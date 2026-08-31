import json
from datetime import timedelta
from functools import lru_cache

from minio import Minio

from backend.core.config import get_settings


@lru_cache
def get_minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )


@lru_cache
def _get_public_minio_client() -> Minio:
    """Same server, addressed the way a browser can actually reach it.

    Only for `presigned_get_url` below. A presigned URL's signature is computed over the
    request as built for a specific host, so it can't be generated with the internal
    `minio_endpoint` client and then have its host swapped afterwards — that invalidates
    the signature. This client exists purely to sign against the right host from the
    start. Same credentials/bucket either way; `minio_public_endpoint` is the same
    "unset -> fall back to minio_endpoint" knob `public_object_url` already uses.

    `region="us-east-1"` (MinIO's default when MINIO_REGION isn't set) is required here,
    not optional: without a region fixed at construction, minio-py's presigning path calls
    GetBucketLocation against the client's OWN configured endpoint to discover it — i.e.
    this client would try to reach `localhost:9000` from inside the backend container to
    sign a URL that then also points at `localhost:9000`, which fails every time (that
    address means "this container" from in here, not the host machine). Passing the
    region up front skips that lookup entirely; presigning becomes pure local signing
    math with no network call, so it can't fail this way regardless of what
    `minio_public_endpoint` resolves to.
    """
    settings = get_settings()
    return Minio(
        settings.minio_public_endpoint or settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        region="us-east-1",
    )


def ensure_bucket(bucket: str) -> None:
    client = get_minio_client()
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def ensure_public_read_bucket(bucket: str) -> None:
    """Bucket for project marketing images — public GetObject so the frontend can
    load images directly.

    Unlike the internal document bucket (`minio_bucket_documents`), which must stay private.
    """
    ensure_bucket(bucket)
    client = get_minio_client()
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"AWS": ["*"]},
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/*"],
            }
        ],
    }
    client.set_bucket_policy(bucket, json.dumps(policy))


def public_object_url(bucket: str, object_name: str) -> str:
    """Public URL for an object — FOR THE BROWSER, not for the backend.

    Uses `minio_public_endpoint` rather than `minio_endpoint`: inside Docker the
    backend reaches MinIO via the service name `minio:9000`, but this URL is
    returned to the frontend and rendered in an <img> tag, and a browser on the
    host machine cannot resolve the hostname `minio` — the image would break. If
    the variable is unset, falls back to `minio_endpoint` (correct when running
    the backend outside Docker).
    """
    settings = get_settings()
    scheme = "https" if settings.minio_secure else "http"
    endpoint = settings.minio_public_endpoint or settings.minio_endpoint
    return f"{scheme}://{endpoint}/{bucket}/{object_name}"


def presigned_get_url(bucket: str, object_name: str, expires_minutes: int = 10) -> str:
    """Temporary signed link to view a file in a private bucket (internal document
    store) without switching the bucket to public-read.

    Signed against `minio_public_endpoint` (see `_get_public_minio_client`), not the
    internal `minio_endpoint` — this URL is opened directly in a Sale's browser tab from
    a citation chip, and a browser outside the Docker network cannot resolve the internal
    service hostname (`minio`). Without this, the link 404s/hangs for anyone but a
    process running inside the same Docker network.
    """
    client = _get_public_minio_client()
    return client.presigned_get_object(bucket, object_name, expires=timedelta(minutes=expires_minutes))
