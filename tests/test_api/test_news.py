from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.mysql_client import Base, get_db
from backend.core.security import create_access_token
from backend.main import app
from backend.models.news_article import NewsArticle
from backend.models.user import User


@pytest.fixture
def news_db() -> Iterator[sessionmaker[Session]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[User.__table__, NewsArticle.__table__])
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add_all(
            [
                User(id=1, username="sale_news", email="sale-news@example.com", hashed_password="unused", role="sale"),
                User(
                    id=2, username="admin_news", email="admin-news@example.com", hashed_password="unused", role="admin"
                ),
                User(
                    id=3, username="other_sale", email="other-sale@example.com", hashed_password="unused", role="sale"
                ),
            ]
        )
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def news_client(client, news_db, monkeypatch):
    def override_db():
        db = news_db()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr("backend.routers.news.log_event", lambda *_args, **_kwargs: None)
    app.dependency_overrides[get_db] = override_db
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _headers(username: str, role: str) -> dict[str, str]:
    token = create_access_token(subject=username, role=role)
    return {"Authorization": f"Bearer {token}"}


def _article(**overrides):
    payload = {
        "title": "Tiến độ mới nhất tại Vinhomes Ocean Park 2",
        "summary": "Cập nhật các hạng mục vừa hoàn thiện trong tháng.",
        "content": "Nội dung đã được Sale kiểm tra trước khi gửi Admin duyệt. " * 3,
        "image_url": None,
        "topic": "project_progress",
        "project_names": ["Vinhomes Ocean Park 2"],
    }
    payload.update(overrides)
    return payload


def test_draft_is_private_until_admin_approves(news_client):
    sale_headers = _headers("sale_news", "sale")
    admin_headers = _headers("admin_news", "admin")

    created = news_client.post("/api/v1/sale/news", json=_article(), headers=sale_headers)
    assert created.status_code == 201
    article_id = created.json()["id"]
    assert created.json()["status"] == "draft"
    assert created.json()["canonical_url"] == f"auremont://news/{article_id}"
    assert created.json()["source_id"] == "auremont"
    assert created.json()["author_id"] == 1
    assert news_client.get("/api/v1/news").json()["total"] == 0

    submitted = news_client.post(f"/api/v1/sale/news/{article_id}/submit", headers=sale_headers)
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "pending_review"
    assert news_client.get("/api/v1/news").json()["total"] == 0

    approved = news_client.post(
        f"/api/v1/admin/news/{article_id}/approve",
        json={"note": "Nội dung đạt yêu cầu."},
        headers=admin_headers,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "published"

    public_feed = news_client.get("/api/v1/news")
    assert public_feed.status_code == 200
    assert public_feed.json()["total"] == 1
    assert public_feed.json()["items"][0]["content"].startswith("Nội dung")


def test_sale_cannot_attach_an_external_source(news_client):
    payload = _article()
    payload["source_url"] = "https://example.com/imported-news"

    response = news_client.post("/api/v1/sale/news", json=payload, headers=_headers("sale_news", "sale"))

    assert response.status_code == 422


def test_admin_can_request_changes_and_sale_can_resubmit(news_client):
    sale_headers = _headers("sale_news", "sale")
    admin_headers = _headers("admin_news", "admin")
    article_id = news_client.post("/api/v1/sale/news", json=_article(), headers=sale_headers).json()["id"]
    news_client.post(f"/api/v1/sale/news/{article_id}/submit", headers=sale_headers)

    returned = news_client.post(
        f"/api/v1/admin/news/{article_id}/request-changes",
        json={"note": "Bổ sung mốc thời gian hoàn thành."},
        headers=admin_headers,
    )
    assert returned.status_code == 200
    assert returned.json()["status"] == "changes_requested"

    updated = news_client.put(
        f"/api/v1/sale/news/{article_id}",
        json=_article(content="Đã bổ sung mốc hoàn thành ngày 29/08/2026. " * 3),
        headers=sale_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "draft"
    assert updated.json()["review_note"] is None
    assert news_client.post(f"/api/v1/sale/news/{article_id}/submit", headers=sale_headers).status_code == 200


def test_role_and_ownership_boundaries(news_client):
    sale_headers = _headers("sale_news", "sale")
    other_headers = _headers("other_sale", "sale")
    article_id = news_client.post("/api/v1/sale/news", json=_article(), headers=sale_headers).json()["id"]

    assert news_client.post("/api/v1/sale/news", json=_article()).status_code == 401
    assert news_client.get("/api/v1/admin/news", headers=sale_headers).status_code == 403
    assert news_client.put(f"/api/v1/sale/news/{article_id}", json=_article(), headers=other_headers).status_code == 404
    assert news_client.delete(f"/api/v1/sale/news/{article_id}", headers=other_headers).status_code == 404
