"""The B2B subscription flow end to end: quote, apply, approve, then change the plan.

Every test drives the HTTP surface rather than the service directly, because the rules
that matter here are authorization rules — who may read a subscription, who may change it
— and those live in the router's dependencies, not in `billing_service`.

The database is a fresh in-memory SQLite per test with the three plans seeded by hand: the
migration seeds them in production, but `Base.metadata.create_all` does not run migrations,
so the fixture has to put the same rows there itself.
"""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core.mysql_client import Base, get_db
from backend.core.security import create_access_token, hash_password
from backend.main import app
from backend.models.billing import (
    Organization,
    OrganizationMember,
    Plan,
    Subscription,
    SubscriptionRequest,
    UsageMonthly,
)
from backend.models.user import User
from backend.utils.time import utcnow

_TABLES = [
    User.__table__,
    Plan.__table__,
    Organization.__table__,
    OrganizationMember.__table__,
    Subscription.__table__,
    UsageMonthly.__table__,
    SubscriptionRequest.__table__,
]


def _seed_plans(db: Session) -> None:
    """The same three rows the migration inserts, so tests price against real numbers."""
    db.add_all(
        [
            Plan(
                id="starter",
                name="Starter",
                price_per_seat_vnd=390_000,
                min_seats=1,
                conversations_per_seat=150,
                overage_price_vnd=2_000,
                sort_order=1,
            ),
            Plan(
                id="growth",
                name="Growth",
                price_per_seat_vnd=550_000,
                min_seats=3,
                conversations_per_seat=400,
                overage_price_vnd=2_000,
                sort_order=2,
            ),
            Plan(
                id="enterprise",
                name="Enterprise",
                price_per_seat_vnd=420_000,
                min_seats=20,
                conversations_per_seat=None,
                overage_price_vnd=2_000,
                sort_order=3,
            ),
        ]
    )


@pytest.fixture
def billing_db() -> Iterator[sessionmaker[Session]]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=_TABLES)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        _seed_plans(db)
        db.add_all(
            [
                User(
                    id=1,
                    username="admin_billing",
                    email="admin-billing@example.com",
                    hashed_password="unused",
                    role="admin",
                ),
                User(
                    id=2,
                    username="unaffiliated_sale",
                    email="unaffiliated@example.com",
                    hashed_password="unused",
                    role="sale",
                ),
            ]
        )
        db.commit()
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def billing_client(client, billing_db, monkeypatch):
    def override_db():
        db = billing_db()
        try:
            yield db
        finally:
            db.close()

    monkeypatch.setattr("backend.routers.billing.log_event", lambda *_a, **_k: None)
    monkeypatch.setattr("backend.routers.admin_billing.log_event", lambda *_a, **_k: None)
    app.dependency_overrides[get_db] = override_db
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _headers(username: str, role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(subject=username, role=role)}"}


def _application(**overrides) -> dict:
    payload = {
        "plan_id": "growth",
        "seats": 5,
        "company_name": "Sàn Bất Động Sản Minh Khang",
        "contact_name": "Nguyễn Minh Khang",
        "contact_email": "khang@minhkhang.vn",
        "contact_phone": "0912345678",
        "password": "MatKhauRatManh123",
    }
    payload.update(overrides)
    return payload


def test_plans_are_public_and_ordered(billing_client):
    """The pricing page renders unauthenticated, so this must not require a token."""
    response = billing_client.get("/api/v1/billing/plans")

    assert response.status_code == 200
    plans = response.json()
    assert [plan["id"] for plan in plans] == ["starter", "growth", "enterprise"]
    assert plans[1]["price_per_seat_vnd"] == 550_000
    assert plans[2]["conversations_per_seat"] is None


def test_quote_multiplies_seats_by_the_seeded_price(billing_client):
    response = billing_client.get("/api/v1/billing/quote", params={"plan_id": "growth", "seats": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["monthly_total_vnd"] == 550_000 * 5
    assert body["included_conversations"] == 400 * 5


def test_quote_refuses_a_seat_count_below_the_plan_minimum(billing_client):
    """Enterprise's per-seat price is a volume discount; honouring it at 3 seats would
    sell the cheapest rate to the smallest customer."""
    response = billing_client.get("/api/v1/billing/quote", params={"plan_id": "enterprise", "seats": 3})

    assert response.status_code == 422
    assert "20 seat" in response.json()["detail"]


def test_application_stores_the_price_it_was_quoted(billing_client, billing_db):
    response = billing_client.post("/api/v1/billing/subscription-requests", json=_application())

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "pending"
    assert body["quoted_monthly_total_vnd"] == 550_000 * 5

    with billing_db() as db:
        stored = db.get(SubscriptionRequest, body["id"])
        assert stored.hashed_password and stored.hashed_password != "MatKhauRatManh123"


def test_application_creates_no_account_until_an_admin_approves(billing_client, billing_db):
    billing_client.post("/api/v1/billing/subscription-requests", json=_application())

    with billing_db() as db:
        assert db.query(User).filter(User.email == "khang@minhkhang.vn").one_or_none() is None
        assert db.query(Organization).count() == 0


def test_a_second_application_on_the_same_email_is_refused(billing_client):
    billing_client.post("/api/v1/billing/subscription-requests", json=_application())

    response = billing_client.post("/api/v1/billing/subscription-requests", json=_application())

    assert response.status_code == 409
    assert "chờ duyệt" in response.json()["detail"]


def test_approval_provisions_workspace_owner_and_subscription(billing_client, billing_db):
    """One transaction, or none: a workspace with no owner is worse than a failed approval
    because nothing in the product knows how to finish one."""
    created = billing_client.post("/api/v1/billing/subscription-requests", json=_application()).json()

    response = billing_client.patch(
        f"/api/v1/admin/billing/subscription-requests/{created['id']}",
        json={"status": "approved", "review_note": "Đã xác nhận chuyển khoản."},
        headers=_headers("admin_billing", "admin"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"

    with billing_db() as db:
        owner = db.query(User).filter(User.email == "khang@minhkhang.vn").one()
        assert owner.role == "sale"

        organization = db.query(Organization).one()
        assert organization.owner_user_id == owner.id

        membership = db.query(OrganizationMember).one()
        assert membership.role == "owner"

        subscription = db.query(Subscription).one()
        assert (subscription.plan_id, subscription.seats, subscription.status) == ("growth", 5, "active")

        assert db.get(SubscriptionRequest, created["id"]).hashed_password is None


def test_approving_twice_is_refused(billing_client):
    created = billing_client.post("/api/v1/billing/subscription-requests", json=_application()).json()
    approve = {"status": "approved"}
    headers = _headers("admin_billing", "admin")

    billing_client.patch(f"/api/v1/admin/billing/subscription-requests/{created['id']}", json=approve, headers=headers)
    second = billing_client.patch(
        f"/api/v1/admin/billing/subscription-requests/{created['id']}", json=approve, headers=headers
    )

    assert second.status_code == 409


def test_rejecting_annotates_without_creating_an_account(billing_client, billing_db):
    created = billing_client.post("/api/v1/billing/subscription-requests", json=_application()).json()

    response = billing_client.patch(
        f"/api/v1/admin/billing/subscription-requests/{created['id']}",
        json={"status": "rejected", "review_note": "Chưa đủ thông tin hoá đơn."},
        headers=_headers("admin_billing", "admin"),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    with billing_db() as db:
        assert db.query(User).filter(User.email == "khang@minhkhang.vn").one_or_none() is None


def test_a_sale_cannot_reach_the_admin_review_queue(billing_client):
    response = billing_client.get(
        "/api/v1/admin/billing/subscription-requests", headers=_headers("unaffiliated_sale", "sale")
    )

    assert response.status_code == 403


def _approved_owner(billing_client, billing_db, **overrides) -> str:
    """Run an application through approval and return the owner's login."""
    payload = _application(**overrides)
    created = billing_client.post("/api/v1/billing/subscription-requests", json=payload).json()
    billing_client.patch(
        f"/api/v1/admin/billing/subscription-requests/{created['id']}",
        json={"status": "approved"},
        headers=_headers("admin_billing", "admin"),
    )
    return payload["contact_email"]


def test_owner_reads_their_own_subscription(billing_client, billing_db):
    owner_email = _approved_owner(billing_client, billing_db)

    response = billing_client.get("/api/v1/billing/my-subscription", headers=_headers(owner_email, "sale"))

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["id"] == "growth"
    assert body["seats"] == 5
    assert body["seats_used"] == 1
    assert body["monthly_total_vnd"] == 550_000 * 5
    assert body["usage"]["conversations_included"] == 400 * 5


def test_a_sale_with_no_workspace_gets_404_not_403(billing_client):
    """Nothing to be forbidden from: the account was never added to a workspace."""
    response = billing_client.get("/api/v1/billing/my-subscription", headers=_headers("unaffiliated_sale", "sale"))

    assert response.status_code == 404


def test_upgrade_applies_immediately(billing_client, billing_db):
    owner_email = _approved_owner(billing_client, billing_db)

    response = billing_client.post(
        "/api/v1/billing/subscription/change",
        json={"seats": 8},
        headers=_headers(owner_email, "sale"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["seats"] == 8
    assert body["pending_seats"] is None
    assert body["monthly_total_vnd"] == 550_000 * 8


def test_downgrade_waits_for_the_next_renewal(billing_client, billing_db):
    """The customer already paid for this period; refunding part of a month is a finance
    decision this endpoint should not make on its own."""
    owner_email = _approved_owner(billing_client, billing_db)

    response = billing_client.post(
        "/api/v1/billing/subscription/change",
        json={"plan_id": "starter", "seats": 3},
        headers=_headers(owner_email, "sale"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["id"] == "growth", "the paid plan must stay live until the period ends"
    assert body["pending_plan_id"] == "starter"
    assert body["pending_seats"] == 3


def test_seats_cannot_drop_below_the_people_already_in_the_workspace(billing_client, billing_db):
    owner_email = _approved_owner(billing_client, billing_db)
    with billing_db() as db:
        organization = db.query(Organization).one()
        for index in range(3):
            member = User(
                username=f"sale{index}@minhkhang.vn",
                email=f"sale{index}@minhkhang.vn",
                hashed_password=hash_password("x" * 12),
                role="sale",
            )
            db.add(member)
            db.flush()
            db.add(OrganizationMember(organization_id=organization.id, user_id=member.id, role="member"))
        db.commit()

    response = billing_client.post(
        "/api/v1/billing/subscription/change",
        json={"seats": 2},
        headers=_headers(owner_email, "sale"),
    )

    assert response.status_code == 422
    assert "4 thành viên" in response.json()["detail"]


def test_only_the_owner_may_change_the_plan(billing_client, billing_db):
    _approved_owner(billing_client, billing_db)
    with billing_db() as db:
        organization = db.query(Organization).one()
        member = User(
            username="member@minhkhang.vn",
            email="member@minhkhang.vn",
            hashed_password=hash_password("x" * 12),
            role="sale",
        )
        db.add(member)
        db.flush()
        db.add(OrganizationMember(organization_id=organization.id, user_id=member.id, role="member"))
        db.commit()

    response = billing_client.post(
        "/api/v1/billing/subscription/change",
        json={"seats": 9},
        headers=_headers("member@minhkhang.vn", "sale"),
    )

    assert response.status_code == 403


def test_cancelling_keeps_access_until_the_period_ends(billing_client, billing_db):
    owner_email = _approved_owner(billing_client, billing_db)

    response = billing_client.post("/api/v1/billing/subscription/cancel", headers=_headers(owner_email, "sale"))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "cancelled"
    assert body["cancelled_at"] is not None

    with billing_db() as db:
        subscription = db.query(Subscription).one()
        assert subscription.current_period_end > utcnow()


def test_expired_subscription_denies_access(billing_db):
    """`has_access` is what the seat/quota gate will call, so its verdict on a lapsed
    period is checked directly rather than through a route that does not exist yet."""
    from backend.services import billing_service

    with billing_db() as db:
        organization = Organization(name="Hết hạn", slug="het-han", contact_email="a@b.vn")
        db.add(organization)
        db.flush()
        started = utcnow() - timedelta(days=60)
        subscription = Subscription(
            organization_id=organization.id,
            plan_id="starter",
            seats=1,
            status="active",
            current_period_start=started,
            current_period_end=started + timedelta(days=30),
        )
        db.add(subscription)
        db.commit()

        assert billing_service.has_access(subscription) is False
