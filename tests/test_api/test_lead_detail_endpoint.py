"""GET /sale/live-inbox/{id}/lead — the full breakdown behind the badge.

The inbox row only has room for one joined string; this is where a Sale checks the actual
evidence before acting on it.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import SessionChannel, SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.lead import Lead
from backend.models.user import User
from backend.utils.time import utcnow


@pytest.fixture
def sale(db_session):
    user = User(username="sale", email="sale@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def other_sale(db_session):
    user = User(username="sale2", email="sale2@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client_as(db_session):
    def _login(user: User) -> TestClient:
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield _login
    app.dependency_overrides.clear()


def _claimed_session(db, sale: User, *, customer_phone: str | None = "0912345678") -> ChatSession:
    customer = User(
        username=f"cust{db.query(User).count()}",
        email=f"cust{db.query(User).count()}@example.com",
        hashed_password="x",
        role=UserRole.CUSTOMER,
        full_name="Phạm Văn D",
        phone=customer_phone,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)

    session = ChatSession(
        customer_id=customer.id, sale_id=sale.id, status=SessionStatus.SALE_HANDLING, channel=SessionChannel.LIVE
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session, customer


def test_the_full_breakdown_lists_every_fired_signal_with_its_points(client_as, db_session, sale):
    session, customer = _claimed_session(db_session, sale)
    db_session.add(
        Lead(
            customer_id=customer.id,
            tier="hot",
            score=80,
            rule_score=80,
            soft_score=0,
            detection_method="rule+llm",
            urgency="near_term",
            purpose="investment",
            confidence=0.7,
            turn_count=4,
            scored_at=utcnow(),
            signals={
                "flags": {"stated_budget": True, "closing_intent": True, "has_phone": True},
                "weights": {"stated_budget": 30, "closing_intent": 25, "has_phone": 10},
                "llm_reason": "Khách hỏi kỹ về pháp lý và muốn xem nhà tuần này.",
            },
        )
    )
    db_session.commit()

    body = client_as(sale).get(f"/api/v1/sale/live-inbox/{session.id}/lead").json()

    assert body["lead_tier"] == "hot"
    assert body["lead_score"] == 80
    assert body["customer_phone"] == "0912345678"
    assert body["customer_name"] == "Phạm Văn D"
    assert {s["label"]: s["points"] for s in body["signals"]} == {
        "Đã nêu ngân sách": 30,
        "Muốn nhận tài liệu / đặt lịch / được liên hệ": 25,
        "Đã có số điện thoại": 10,
    }
    assert body["signals"][0]["label"] == "Đã nêu ngân sách"
    assert body["llm_reason"] == "Khách hỏi kỹ về pháp lý và muốn xem nhà tuần này."


def test_returns_null_when_nobody_has_been_scored_yet(client_as, db_session, sale):
    session, _customer = _claimed_session(db_session, sale)

    response = client_as(sale).get(f"/api/v1/sale/live-inbox/{session.id}/lead")

    assert response.status_code == 200
    assert response.json() is None


def test_a_sale_cannot_read_another_sales_session(client_as, db_session, sale, other_sale):
    session, customer = _claimed_session(db_session, sale)
    db_session.add(Lead(customer_id=customer.id, tier="hot", score=80, scored_at=utcnow()))
    db_session.commit()

    response = client_as(other_sale).get(f"/api/v1/sale/live-inbox/{session.id}/lead")

    assert response.status_code == 404
