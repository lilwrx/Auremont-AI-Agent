import hashlib
import uuid
from datetime import timedelta
from typing import cast

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.core.config import Settings
from backend.models.news_article import NewsArticle
from backend.models.user import User
from backend.schemas.news import NewsDraftCreate, NewsDraftUpdate, NewsStatus, NewsWorkflowArticleResponse
from backend.utils.time import utcnow

EDITABLE_NEWS_STATUSES = frozenset({"draft", "changes_requested", "rejected"})
REVIEWABLE_NEWS_STATUS = "pending_review"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _content_hash(payload: NewsDraftCreate | NewsDraftUpdate) -> str:
    values = [
        payload.title,
        payload.summary or "",
        payload.content,
        payload.image_url or "",
        payload.topic,
        "\x1f".join(payload.project_names),
    ]
    return _sha256("\x1e".join(values))


def create_news_draft(db: Session, payload: NewsDraftCreate, author: User, settings: Settings) -> NewsArticle:
    now = utcnow()
    unique_marker = uuid.uuid4().hex
    article = NewsArticle(
        url_hash=_sha256(f"auremont-news:{unique_marker}"),
        canonical_url=f"auremont://draft/{unique_marker}",
        source_id="auremont",
        source_name="Auremont",
        title=payload.title,
        summary=payload.summary,
        content=payload.content,
        image_url=payload.image_url,
        topic=payload.topic,
        project_names=payload.project_names,
        status="draft",
        content_hash=_content_hash(payload),
        published_at=None,
        fetched_at=now,
        expires_at=now + timedelta(days=settings.news_default_ttl_days),
        author_id=author.id,
    )
    db.add(article)
    db.flush()
    article.canonical_url = f"auremont://news/{article.id}"
    db.commit()
    db.refresh(article)
    return article


def get_owned_news(db: Session, article_id: int, author_id: int, *, for_update: bool = False) -> NewsArticle:
    statement = select(NewsArticle).where(NewsArticle.id == article_id, NewsArticle.author_id == author_id)
    if for_update:
        statement = statement.with_for_update()
    article = db.scalar(statement)
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bài viết của bạn.")
    return article


def update_news_draft(
    db: Session,
    article_id: int,
    author: User,
    payload: NewsDraftUpdate,
) -> NewsArticle:
    article = get_owned_news(db, article_id, author.id, for_update=True)
    if article.status not in EDITABLE_NEWS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Chỉ có thể sửa bản nháp hoặc bài được yêu cầu chỉnh sửa.",
        )

    article.title = payload.title
    article.summary = payload.summary
    article.content = payload.content
    article.image_url = payload.image_url
    article.canonical_url = f"auremont://news/{article.id}"
    article.source_id = "auremont"
    article.source_name = "Auremont"
    article.topic = payload.topic
    article.project_names = payload.project_names
    article.content_hash = _content_hash(payload)
    article.status = "draft"
    article.review_note = None
    article.reviewer_id = None
    article.reviewed_at = None
    db.commit()
    db.refresh(article)
    return article


def submit_news_for_review(db: Session, article_id: int, author: User) -> NewsArticle:
    article = get_owned_news(db, article_id, author.id, for_update=True)
    if article.status not in EDITABLE_NEWS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Bài viết không ở trạng thái có thể gửi duyệt."
        )
    if not article.content or len(article.content.strip()) < 50:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nội dung bài viết quá ngắn.")

    article.status = REVIEWABLE_NEWS_STATUS
    article.submitted_at = utcnow()
    article.review_note = None
    article.reviewer_id = None
    article.reviewed_at = None
    db.commit()
    db.refresh(article)
    return article


def delete_news_draft(db: Session, article_id: int, author: User) -> None:
    article = get_owned_news(db, article_id, author.id, for_update=True)
    if article.status not in EDITABLE_NEWS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Không thể xóa bài đang duyệt hoặc đã xuất bản."
        )
    db.delete(article)
    db.commit()


def get_review_article(db: Session, article_id: int, *, for_update: bool = False) -> NewsArticle:
    statement = select(NewsArticle).where(NewsArticle.id == article_id)
    if for_update:
        statement = statement.with_for_update()
    article = db.scalar(statement)
    if article is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Không tìm thấy bài viết.")
    return article


def approve_news(db: Session, article_id: int, reviewer: User, note: str | None, settings: Settings) -> NewsArticle:
    article = get_review_article(db, article_id, for_update=True)
    if article.status != REVIEWABLE_NEWS_STATUS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Chỉ có thể duyệt bài đang chờ kiểm duyệt.")
    now = utcnow()
    article.status = "published"
    article.reviewer_id = reviewer.id
    article.review_note = note
    article.reviewed_at = now
    article.published_at = now
    article.expires_at = now + timedelta(days=settings.news_default_ttl_days)
    article.archived_at = None
    db.commit()
    db.refresh(article)
    return article


def return_news_for_changes(db: Session, article_id: int, reviewer: User, note: str) -> NewsArticle:
    return _review_transition(db, article_id, reviewer, "changes_requested", note)


def reject_news(db: Session, article_id: int, reviewer: User, note: str) -> NewsArticle:
    return _review_transition(db, article_id, reviewer, "rejected", note)


def _review_transition(db: Session, article_id: int, reviewer: User, target_status: str, note: str) -> NewsArticle:
    article = get_review_article(db, article_id, for_update=True)
    if article.status != REVIEWABLE_NEWS_STATUS:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Chỉ có thể xử lý bài đang chờ kiểm duyệt.")
    article.status = target_status
    article.reviewer_id = reviewer.id
    article.review_note = note
    article.reviewed_at = utcnow()
    db.commit()
    db.refresh(article)
    return article


def archive_news(db: Session, article_id: int, reviewer: User, note: str | None) -> NewsArticle:
    article = get_review_article(db, article_id, for_update=True)
    if article.status != "published":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Chỉ có thể lưu trữ bài đang xuất bản.")
    now = utcnow()
    article.status = "archived"
    article.archived_at = now
    article.reviewer_id = reviewer.id
    article.review_note = note
    article.reviewed_at = now
    db.commit()
    db.refresh(article)
    return article


def list_sale_news(
    db: Session,
    *,
    author_id: int,
    offset: int,
    limit: int,
    article_status: str | None,
) -> tuple[list[NewsArticle], int]:
    filters = [NewsArticle.author_id == author_id]
    if article_status:
        filters.append(NewsArticle.status == article_status)
    total = db.scalar(select(func.count(NewsArticle.id)).where(*filters)) or 0
    rows = list(
        db.scalars(
            select(NewsArticle)
            .where(*filters)
            .order_by(NewsArticle.updated_at.desc(), NewsArticle.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, total


def list_admin_news(
    db: Session,
    *,
    offset: int,
    limit: int,
    article_status: str | None,
) -> tuple[list[NewsArticle], int]:
    filters = []
    if article_status:
        filters.append(NewsArticle.status == article_status)
    total = db.scalar(select(func.count(NewsArticle.id)).where(*filters)) or 0
    rows = list(
        db.scalars(
            select(NewsArticle)
            .where(*filters)
            .order_by(
                NewsArticle.submitted_at.desc(),
                NewsArticle.updated_at.desc(),
                NewsArticle.id.desc(),
            )
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, total


def workflow_responses(db: Session, articles: list[NewsArticle]) -> list[NewsWorkflowArticleResponse]:
    user_ids = {
        user_id for article in articles for user_id in (article.author_id, article.reviewer_id) if user_id is not None
    }
    users = (
        {user.id: user.username for user in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    )
    return [
        NewsWorkflowArticleResponse(
            id=article.id,
            canonical_url=article.canonical_url,
            source_id=article.source_id,
            source_name=article.source_name,
            title=article.title,
            summary=article.summary,
            content=article.content,
            image_url=article.image_url,
            topic=article.topic,
            project_names=article.project_names or [],
            published_at=article.published_at,
            fetched_at=article.fetched_at,
            status=cast(NewsStatus, article.status),
            author_id=article.author_id,
            author_name=users.get(article.author_id, "Hệ thống") if article.author_id is not None else "Hệ thống",
            reviewer_id=article.reviewer_id,
            reviewer_name=users.get(article.reviewer_id) if article.reviewer_id is not None else None,
            review_note=article.review_note,
            submitted_at=article.submitted_at,
            reviewed_at=article.reviewed_at,
            expires_at=article.expires_at,
            created_at=article.created_at,
            updated_at=article.updated_at,
        )
        for article in articles
    ]


def list_published_news(
    db: Session,
    *,
    offset: int,
    limit: int,
    topic: str | None = None,
    source_id: str | None = None,
    query: str | None = None,
) -> tuple[list[NewsArticle], int]:
    now = utcnow()
    filters = [NewsArticle.status == "published", NewsArticle.expires_at > now]
    if topic:
        filters.append(NewsArticle.topic == topic)
    if source_id:
        filters.append(NewsArticle.source_id == source_id)
    if query:
        pattern = f"%{query.strip()}%"
        filters.append(
            or_(
                NewsArticle.title.ilike(pattern),
                NewsArticle.summary.ilike(pattern),
                NewsArticle.content.ilike(pattern),
            )
        )

    total = db.scalar(select(func.count(NewsArticle.id)).where(*filters)) or 0
    rows = list(
        db.scalars(
            select(NewsArticle)
            .where(*filters)
            .order_by(NewsArticle.published_at.desc(), NewsArticle.fetched_at.desc(), NewsArticle.id.desc())
            .offset(offset)
            .limit(limit)
        )
    )
    return rows, total
