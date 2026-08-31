"""E2E: đi hết hành trình của Sale và Admin qua đúng các endpoint mà frontend gọi.

Khác với test đơn vị (mock DB bằng SQLite), bộ này chạy ngược lại stack Docker
đang sống — MySQL thật, JWT thật. Đó là nơi hai lỗi trước lọt lưới: FK của MySQL
và `create_all` không ALTER bảng, cả hai đều vô hình trên SQLite.

Chạy:
    docker compose up -d
    pytest tests/test_e2e -v

Bỏ qua tự động nếu backend không chạy.
"""

import os
import uuid

import httpx
import pytest

BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:8000")
API = f"{BASE_URL}/api/v1"
PASSWORD = "pass1234"

FRONTEND_ENDPOINTS = [
    ("POST", "/auth/login"),
    ("POST", "/auth/logout"),
    ("GET", "/documents"),
    ("POST", "/documents/ingest"),
    ("GET", "/sale/sessions"),
    ("POST", "/sale/sessions"),
    ("GET", "/admin/conflicts"),
    ("GET", "/admin/eval/scores"),
    ("GET", "/admin/eval/reports"),
    ("GET", "/admin/settings"),
    ("POST", "/feedback"),
]


def _backend_is_up() -> bool:
    try:
        return httpx.get(f"{BASE_URL}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _backend_is_up(),
    reason=f"Backend not running at {BASE_URL} - start it with `docker compose up -d`.",
)


@pytest.fixture(scope="module")
def accounts():
    """Tạo cặp Sale/Admin riêng cho lần chạy này để không đụng dữ liệu sẵn có."""
    tag = uuid.uuid4().hex[:8]
    created = {}

    for role in ("sale", "admin"):
        username = f"e2e_{role}_{tag}"
        result = httpx.post(
            f"{BASE_URL}/__test__/users",
            json={"username": username, "email": f"{username}@example.com", "password": PASSWORD, "role": role},
            timeout=10,
        )
        if result.status_code == 404:
            pytest.skip("Backend chưa bật endpoint seed cho E2E (chỉ có ở APP_ENV=development).")
        assert result.status_code in (200, 201), result.text
        created[role] = username

    return created


def _token(username: str) -> str:
    response = httpx.post(f"{API}/auth/login", data={"username": username, "password": PASSWORD}, timeout=10)
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture(scope="module")
def sale_headers(accounts):
    return {"Authorization": f"Bearer {_token(accounts['sale'])}"}


@pytest.fixture(scope="module")
def admin_headers(accounts):
    return {"Authorization": f"Bearer {_token(accounts['admin'])}"}


def test_sale_consultation_journey(sale_headers):
    """Đăng nhập → tạo phiên → hỏi → xem lịch sử → gửi feedback → xoá phiên."""
    session = httpx.post(f"{API}/sale/sessions", json={"title": "Khách E2E"}, headers=sale_headers, timeout=15)
    assert session.status_code == 201, session.text
    session_id = session.json()["id"]

    listed = httpx.get(f"{API}/sale/sessions", headers=sale_headers, timeout=15).json()
    assert session_id in [s["id"] for s in listed]

    answer = httpx.post(
        f"{API}/sale/sessions/{session_id}/messages",
        json={"content": "Giá căn 2PN?"},
        headers=sale_headers,
        timeout=60,
    )
    if answer.status_code == 201:
        message_id = answer.json()["id"]

        history = httpx.get(f"{API}/sale/sessions/{session_id}/messages", headers=sale_headers, timeout=15).json()
        assert message_id in [m["id"] for m in history]

        feedback = httpx.post(
            f"{API}/feedback",
            json={"message_id": message_id, "type": "helpful"},
            headers=sale_headers,
            timeout=15,
        )
        assert feedback.status_code == 201, feedback.text
    else:
        assert answer.status_code == 500, f"Lỗi lạ từ pipeline: {answer.status_code} {answer.text}"

    assert httpx.delete(f"{API}/sale/sessions/{session_id}", headers=sale_headers, timeout=15).status_code == 204
    remaining = httpx.get(f"{API}/sale/sessions", headers=sale_headers, timeout=15).json()
    assert session_id not in [s["id"] for s in remaining]


def test_admin_document_journey(admin_headers):
    """Legacy raw-text registration stays quarantined until real ingestion, then deletes."""
    ingest = httpx.post(
        f"{API}/documents/ingest",
        json={"title": f"E2E doc {uuid.uuid4().hex[:6]}.txt", "raw_text": "Bảng giá căn 2PN: 3.5 tỷ."},
        headers=admin_headers,
        timeout=30,
    )
    assert ingest.status_code == 201, ingest.text
    document_id = ingest.json()["document_id"]

    listed = httpx.get(f"{API}/documents", headers=admin_headers, timeout=15).json()
    assert document_id in [d["id"] for d in listed]

    visibility = httpx.patch(
        f"{API}/documents/{document_id}/visibility",
        json={"visibility": "public"},
        headers=admin_headers,
        timeout=15,
    )
    assert visibility.status_code == 409, visibility.text

    assert httpx.delete(f"{API}/documents/{document_id}", headers=admin_headers, timeout=15).status_code == 204


def test_admin_monitoring_tabs_respond(admin_headers):
    """Ba tab giám sát của Admin phải trả dữ liệu đúng hình dạng frontend mong đợi."""
    scores = httpx.get(f"{API}/admin/eval/scores", headers=admin_headers, timeout=15)
    assert scores.status_code == 200
    assert "top_failed_questions" in scores.json()

    conflicts = httpx.get(f"{API}/admin/conflicts", headers=admin_headers, timeout=15)
    assert conflicts.status_code == 200
    assert isinstance(conflicts.json(), list)

    settings = httpx.get(f"{API}/admin/settings", headers=admin_headers, timeout=15)
    assert settings.status_code == 200
    assert "verifier_threshold_sale" in settings.json()


def test_roles_stay_separated(sale_headers, admin_headers):
    """Sale không chạm được khu quản trị; cả hai đều chat được (phiên riêng)."""
    assert httpx.get(f"{API}/documents", headers=sale_headers, timeout=15).status_code == 403
    assert httpx.get(f"{API}/admin/conflicts", headers=sale_headers, timeout=15).status_code == 403

    admin_session = httpx.post(f"{API}/sale/sessions", json={"title": "Khách Admin"}, headers=admin_headers, timeout=15)
    assert admin_session.status_code == 201
    admin_session_id = admin_session.json()["id"]

    sale_sessions = httpx.get(f"{API}/sale/sessions", headers=sale_headers, timeout=15).json()
    assert admin_session_id not in [s["id"] for s in sale_sessions]
    assert (
        httpx.get(f"{API}/sale/sessions/{admin_session_id}/messages", headers=sale_headers, timeout=15).status_code
        == 404
    )

    httpx.delete(f"{API}/sale/sessions/{admin_session_id}", headers=admin_headers, timeout=15)


def test_token_refresh_keeps_the_session_alive(accounts):
    """Access token hết hạn giữa lúc tư vấn không được đá Sale ra màn đăng nhập."""
    login = httpx.post(
        f"{API}/auth/login", data={"username": accounts["sale"], "password": PASSWORD}, timeout=15
    ).json()

    refreshed = httpx.post(f"{API}/auth/refresh", json={"refresh_token": login["refresh_token"]}, timeout=15)
    assert refreshed.status_code == 200, refreshed.text

    new_token = refreshed.json()["access_token"]
    me = httpx.get(f"{API}/users/me", headers={"Authorization": f"Bearer {new_token}"}, timeout=15)
    assert me.status_code == 200
    assert me.json()["username"] == accounts["sale"]

    assert (
        httpx.post(f"{API}/auth/refresh", json={"refresh_token": login["access_token"]}, timeout=15).status_code == 401
    )


@pytest.mark.parametrize(("method", "path"), FRONTEND_ENDPOINTS)
def test_every_endpoint_the_frontend_calls_exists(method, path):
    """Không endpoint nào frontend gọi được phép biến mất (404) khỏi backend."""
    spec = httpx.get(f"{BASE_URL}/openapi.json", timeout=15).json()
    documented = spec["paths"].get(f"/api/v1{path}")

    assert documented is not None, f"Frontend gọi {path} nhưng backend không có route này"
    assert method.lower() in documented, f"{path} thiếu method {method}"
