"""Auth: login, refresh, logout, và phân quyền theo role."""

import pytest
from fastapi.testclient import TestClient

from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.core.security import create_access_token
from backend.main import app
from backend.repositories.user import create_user

PASSWORD = "pass1234"


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def users(db_session):
    sale = create_user(db_session, username="sale1", email="s@x.com", password=PASSWORD, role=UserRole.SALE)
    admin = create_user(db_session, username="adm1", email="a@x.com", password=PASSWORD, role=UserRole.ADMIN)
    return sale, admin


def _login(client: TestClient, username: str) -> dict:
    response = client.post("/api/v1/auth/login", data={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()


def test_login_returns_tokens_and_role(client, users):
    body = _login(client, "adm1")
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == "admin"


def test_login_rejects_wrong_password(client, users):
    response = client.post("/api/v1/auth/login", data={"username": "sale1", "password": "sai-mat-khau"})
    assert response.status_code == 401


def test_refresh_issues_a_working_access_token(client, users):
    refresh_token = _login(client, "sale1")["refresh_token"]

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200, response.text

    new_access = response.json()["access_token"]
    me = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {new_access}"})
    assert me.status_code == 200
    assert me.json()["username"] == "sale1"


def test_access_token_cannot_be_used_to_refresh(client, users):
    """Nếu không chặn, một access token bị lộ có thể tự gia hạn vô hạn."""
    access_token = _login(client, "sale1")["access_token"]

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


def test_refresh_rejects_garbage_and_unknown_users(client, users):
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": "khong-phai-jwt"}).status_code == 401

    orphan = create_access_token(subject="nguoi-khong-ton-tai", role="sale")
    assert client.post("/api/v1/auth/refresh", json={"refresh_token": orphan}).status_code == 401


def test_logout_requires_authentication(client, users):
    assert client.post("/api/v1/auth/logout").status_code == 401

    access_token = _login(client, "sale1")["access_token"]
    assert client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access_token}"}).status_code == 204


def test_admin_only_routes_reject_sale(client, users):
    sale_token = _login(client, "sale1")["access_token"]
    admin_token = _login(client, "adm1")["access_token"]

    assert client.get("/api/v1/documents", headers={"Authorization": f"Bearer {sale_token}"}).status_code == 403
    assert client.get("/api/v1/documents", headers={"Authorization": f"Bearer {admin_token}"}).status_code == 200
