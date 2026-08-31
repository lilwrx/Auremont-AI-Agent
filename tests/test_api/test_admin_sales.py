from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import MessageSender, SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.core.security import verify_password
from backend.main import app
from backend.models.audit_log import AuditLog
from backend.models.chat_session import ChatSession
from backend.models.message import Message
from backend.models.user import User
from backend.routers import admin_sales
from backend.utils.time import utcnow


@pytest.fixture
def users(db_session):
    admin = User(username="admin-board", email="admin-board@example.com", hashed_password="x", role=UserRole.ADMIN)
    first = User(username="sale-one", email="sale-one@example.com", hashed_password="x", role=UserRole.SALE)
    second = User(username="sale-two", email="sale-two@example.com", hashed_password="x", role=UserRole.SALE)
    customer = User(username="customer-one", email="customer@example.com", hashed_password="x", role=UserRole.CUSTOMER)
    db_session.add_all([admin, first, second, customer])
    db_session.commit()
    for user in (admin, first, second, customer):
        db_session.refresh(user)
    return admin, first, second, customer


@pytest.fixture
def client(db_session, users, monkeypatch):
    admin, *_ = users
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: admin
    monkeypatch.setattr(admin_sales, "log_event", lambda *_args, **_kwargs: None)
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_sales_board_uses_real_live_sessions_and_activity(client, db_session, users):
    _admin, first, _second, customer = users
    live = ChatSession(sale_id=first.id, customer_id=customer.id, status=SessionStatus.SALE_HANDLING)
    waiting = ChatSession(visitor_token="anonymous-token", status=SessionStatus.WAITING_SALE)
    db_session.add_all([live, waiting])
    db_session.commit()
    db_session.refresh(live)
    db_session.add(Message(session_id=live.id, sender=MessageSender.SALE, content="Tôi đang hỗ trợ anh/chị."))
    db_session.add(
        AuditLog(
            event="chat.handoff.reply",
            user_id=first.id,
            username=first.username,
            created_at=utcnow() - timedelta(minutes=1),
        )
    )
    db_session.commit()

    response = client.get("/api/v1/admin/sales")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["summary"]["waiting_customers"] == 1
    assert body["summary"]["live_customers"] == 1
    sale = next(row for row in body["sales"] if row["id"] == first.id)
    assert sale["presence"] == "busy"
    assert sale["active_chat_sessions"] == 1
    assert sale["interaction_rate"] == 100.0
    assert sale["conversion_rate"] is None


def test_admin_can_create_an_active_sale_account(client, db_session):
    response = client.post(
        "/api/v1/admin/sales",
        json={
            "username": "sale.new",
            "email": "SALE.NEW@EXAMPLE.COM",
            "password": "SaleSecure123",
            "is_active": True,
        },
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["username"] == "sale.new"
    assert body["email"] == "sale.new@example.com"
    assert body["is_active"] is True
    assert body["presence"] == "offline"
    assert "password" not in body
    assert "hashed_password" not in body

    sale = db_session.query(User).filter(User.username == "sale.new").one()
    assert sale.role == UserRole.SALE
    assert sale.is_active is True
    assert sale.hashed_password != "SaleSecure123"
    assert verify_password("SaleSecure123", sale.hashed_password) is True


@pytest.mark.parametrize(
    ("username", "email", "expected_detail"),
    [
        ("SALE-ONE", "different@example.com", "Tên đăng nhập đã được sử dụng."),
        ("different-sale", "SALE-ONE@EXAMPLE.COM", "Email đã được sử dụng."),
    ],
)
def test_create_sale_rejects_case_insensitive_duplicates(client, username, email, expected_detail):
    response = client.post(
        "/api/v1/admin/sales",
        json={"username": username, "email": email, "password": "SaleSecure123", "is_active": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == expected_detail


def test_sale_cannot_create_another_sale(client, users):
    _admin, sale, *_ = users
    app.dependency_overrides[get_current_user] = lambda: sale

    response = client.post(
        "/api/v1/admin/sales",
        json={
            "username": "sale.forbidden",
            "email": "sale.forbidden@example.com",
            "password": "SaleSecure123",
        },
    )

    assert response.status_code == 403


def test_busy_sale_must_be_reassigned_before_deactivation(client, db_session, users):
    _admin, first, _second, customer = users
    db_session.add(ChatSession(sale_id=first.id, customer_id=customer.id, status=SessionStatus.SALE_HANDLING))
    db_session.commit()

    response = client.patch(f"/api/v1/admin/sales/{first.id}/active", json={"is_active": False})

    assert response.status_code == 409
    db_session.refresh(first)
    assert first.is_active is True


def test_admin_can_assign_waiting_customer_to_an_active_sale(client, db_session, users):
    _admin, _first, second, _customer = users
    waiting = ChatSession(visitor_token="waiting-token", status=SessionStatus.WAITING_SALE)
    db_session.add(waiting)
    db_session.commit()
    db_session.refresh(waiting)

    response = client.post(
        "/api/v1/admin/sales/reassign",
        json={"session_id": waiting.id, "to_sale_id": second.id},
    )

    assert response.status_code == 200, response.text
    db_session.refresh(waiting)
    assert waiting.sale_id == second.id
    assert waiting.status == SessionStatus.SALE_HANDLING
    assert response.json()["current_sale_name"] == second.username
