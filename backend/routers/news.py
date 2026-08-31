import uuid
from io import BytesIO
from pathlib import PurePath

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.core.audit import log_event
from backend.core.config import Settings, get_settings
from backend.core.deps import require_role
from backend.core.enums import UserRole
from backend.core.minio_client import ensure_public_read_bucket, get_minio_client, public_object_url
from backend.core.mysql_client import get_db
from backend.models.news_article import NewsArticle
from backend.models.user import User
from backend.schemas.news import (
    NewsArticleResponse,
    NewsDraftCreate,
    NewsDraftUpdate,
    NewsImageUploadResponse,
    NewsListResponse,
    NewsReviewRequest,
    NewsReviewRequiredRequest,
    NewsStatus,
    NewsTopic,
    NewsWorkflowArticleResponse,
    NewsWorkflowListResponse,
)
from backend.services.news_service import (
    approve_news,
    archive_news,
    create_news_draft,
    delete_news_draft,
    get_owned_news,
    get_review_article,
    list_admin_news,
    list_published_news,
    list_sale_news,
    reject_news,
    return_news_for_changes,
    submit_news_for_review,
    update_news_draft,
    workflow_responses,
)
from backend.utils.time import utcnow

router = APIRouter(tags=["News"])

ALLOWED_NEWS_IMAGE_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
MAX_NEWS_IMAGE_BYTES = 5 * 1024 * 1024


def _workflow_response(db: Session, article: NewsArticle) -> NewsWorkflowArticleResponse:
    return workflow_responses(db, [article])[0]


@router.get("/news", response_model=NewsListResponse)
def get_news(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=12, ge=1, le=48),
    topic: NewsTopic | None = None,
    source_id: str | None = Query(default=None, max_length=50),
    q: str | None = Query(default=None, max_length=100),
    db: Session = Depends(get_db),
) -> NewsListResponse:
    """Public feed. Draft and review states can never appear here."""

    rows, total = list_published_news(
        db,
        offset=offset,
        limit=limit,
        topic=topic,
        source_id=source_id,
        query=q,
    )
    return NewsListResponse(
        items=[NewsArticleResponse.model_validate(row) for row in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.get("/news/{article_id}", response_model=NewsArticleResponse)
def get_news_article(article_id: int, db: Session = Depends(get_db)) -> NewsArticle:
    row = db.scalar(
        select(NewsArticle).where(
            NewsArticle.id == article_id,
            NewsArticle.status == "published",
            NewsArticle.expires_at > utcnow(),
        )
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bài viết.")
    return row


@router.get("/sale/news", response_model=NewsWorkflowListResponse)
def get_my_news(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    article_status: NewsStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    sale: User = Depends(require_role(UserRole.SALE)),
) -> NewsWorkflowListResponse:
    rows, total = list_sale_news(
        db,
        author_id=sale.id,
        offset=offset,
        limit=limit,
        article_status=article_status,
    )
    return NewsWorkflowListResponse(items=workflow_responses(db, rows), total=total, offset=offset, limit=limit)


@router.get("/sale/news/{article_id}", response_model=NewsWorkflowArticleResponse)
def get_my_news_article(
    article_id: int,
    db: Session = Depends(get_db),
    sale: User = Depends(require_role(UserRole.SALE)),
) -> NewsWorkflowArticleResponse:
    return _workflow_response(db, get_owned_news(db, article_id, sale.id))


@router.post("/sale/news", response_model=NewsWorkflowArticleResponse, status_code=status.HTTP_201_CREATED)
def create_my_news(
    payload: NewsDraftCreate,
    db: Session = Depends(get_db),
    sale: User = Depends(require_role(UserRole.SALE)),
    settings: Settings = Depends(get_settings),
) -> NewsWorkflowArticleResponse:
    article = create_news_draft(db, payload, sale, settings)
    log_event("news.draft.created", user_id=sale.id, username=sale.username, article_id=article.id)
    return _workflow_response(db, article)


@router.put("/sale/news/{article_id}", response_model=NewsWorkflowArticleResponse)
def update_my_news(
    article_id: int,
    payload: NewsDraftUpdate,
    db: Session = Depends(get_db),
    sale: User = Depends(require_role(UserRole.SALE)),
) -> NewsWorkflowArticleResponse:
    article = update_news_draft(db, article_id, sale, payload)
    log_event("news.draft.updated", user_id=sale.id, username=sale.username, article_id=article.id)
    return _workflow_response(db, article)


@router.post("/sale/news/{article_id}/submit", response_model=NewsWorkflowArticleResponse)
def submit_my_news(
    article_id: int,
    db: Session = Depends(get_db),
    sale: User = Depends(require_role(UserRole.SALE)),
) -> NewsWorkflowArticleResponse:
    article = submit_news_for_review(db, article_id, sale)
    log_event("news.review.submitted", user_id=sale.id, username=sale.username, article_id=article.id)
    return _workflow_response(db, article)


@router.delete("/sale/news/{article_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_my_news(
    article_id: int,
    db: Session = Depends(get_db),
    sale: User = Depends(require_role(UserRole.SALE)),
) -> None:
    delete_news_draft(db, article_id, sale)
    log_event("news.draft.deleted", user_id=sale.id, username=sale.username, article_id=article_id)


@router.post("/sale/news/images", response_model=NewsImageUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_news_image(
    image: UploadFile = File(...),
    sale: User = Depends(require_role(UserRole.SALE)),
    settings: Settings = Depends(get_settings),
) -> NewsImageUploadResponse:
    if image.content_type not in ALLOWED_NEWS_IMAGE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Chỉ hỗ trợ JPG, PNG, WEBP hoặc GIF."
        )
    data = await image.read(MAX_NEWS_IMAGE_BYTES + 1)
    if not data:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Tệp ảnh trống.")
    if len(data) > MAX_NEWS_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail="Ảnh không được vượt quá 5 MB."
        )

    suffix = PurePath(image.filename or "image").suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}[
            image.content_type
        ]
    object_name = f"news/{sale.id}/{uuid.uuid4().hex}{suffix}"
    try:
        ensure_public_read_bucket(settings.minio_bucket_news_images)
        get_minio_client().put_object(
            bucket_name=settings.minio_bucket_news_images,
            object_name=object_name,
            data=BytesIO(data),
            length=len(data),
            content_type=image.content_type,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Không thể lưu ảnh lúc này."
        ) from exc
    log_event("news.image.uploaded", user_id=sale.id, username=sale.username)
    return NewsImageUploadResponse(image_url=public_object_url(settings.minio_bucket_news_images, object_name))


@router.get("/admin/news", response_model=NewsWorkflowListResponse)
def get_admin_news(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    article_status: NewsStatus | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
) -> NewsWorkflowListResponse:
    rows, total = list_admin_news(db, offset=offset, limit=limit, article_status=article_status)
    return NewsWorkflowListResponse(items=workflow_responses(db, rows), total=total, offset=offset, limit=limit)


@router.get("/admin/news/{article_id}", response_model=NewsWorkflowArticleResponse)
def get_admin_news_article(
    article_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_role(UserRole.ADMIN)),
) -> NewsWorkflowArticleResponse:
    return _workflow_response(db, get_review_article(db, article_id))


@router.post("/admin/news/{article_id}/approve", response_model=NewsWorkflowArticleResponse)
def approve_news_article(
    article_id: int,
    payload: NewsReviewRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
    settings: Settings = Depends(get_settings),
) -> NewsWorkflowArticleResponse:
    article = approve_news(db, article_id, admin, payload.note, settings)
    log_event("news.review.approved", user_id=admin.id, username=admin.username, article_id=article.id)
    return _workflow_response(db, article)


@router.post("/admin/news/{article_id}/request-changes", response_model=NewsWorkflowArticleResponse)
def request_news_changes(
    article_id: int,
    payload: NewsReviewRequiredRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> NewsWorkflowArticleResponse:
    article = return_news_for_changes(db, article_id, admin, payload.note)
    log_event("news.review.changes_requested", user_id=admin.id, username=admin.username, article_id=article.id)
    return _workflow_response(db, article)


@router.post("/admin/news/{article_id}/reject", response_model=NewsWorkflowArticleResponse)
def reject_news_article(
    article_id: int,
    payload: NewsReviewRequiredRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> NewsWorkflowArticleResponse:
    article = reject_news(db, article_id, admin, payload.note)
    log_event("news.review.rejected", user_id=admin.id, username=admin.username, article_id=article.id)
    return _workflow_response(db, article)


@router.post("/admin/news/{article_id}/archive", response_model=NewsWorkflowArticleResponse)
def archive_news_article(
    article_id: int,
    payload: NewsReviewRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_role(UserRole.ADMIN)),
) -> NewsWorkflowArticleResponse:
    article = archive_news(db, article_id, admin, payload.note)
    log_event("news.archived", user_id=admin.id, username=admin.username, article_id=article.id)
    return _workflow_response(db, article)
