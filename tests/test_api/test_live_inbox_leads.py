"""What the Sale actually sees: the badge, the contact details, and the queue order.

The ordering rule is the subtle part. Sorting purely by tier lets a steady trickle of HOT
leads starve a COLD customer forever — and that customer is a real person who pressed "gặp
chuyên viên" and is watching a spinner. Waiting past the fairness window outranks any tier.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.core.deps import get_current_user
from backend.core.enums import LeadTier, SessionChannel, SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.lead import Lead
from backend.models.user import User
from backend.services import lead_scoring_service
from backend.utils.time import utcnow


@pytest.fixture
def sale(db_session):
    user = User(username="sale", email="sale@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def client(db_session, sale):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: sale
    yield TestClient(app)
    app.dependency_overrides.clear()


def _waiting_customer(db, *, email: str, tier: LeadTier, waited_minutes: int, phone: str | None = None):
    user = User(
        username=email, email=email, hashed_password="x", role=UserRole.CUSTOMER, full_name="Khách Thử", phone=phone
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    session = ChatSession(
        customer_id=user.id,
        status=SessionStatus.WAITING_SALE,
        channel=SessionChannel.LIVE,
        handoff_requested_at=utcnow() - timedelta(minutes=waited_minutes),
    )
    lead = Lead(
        customer_id=user.id,
        tier=tier,
        score={LeadTier.HOT: 80, LeadTier.WARM: 45, LeadTier.COLD: 5}[tier],
        signals={"flags": {"stated_budget": tier is not LeadTier.COLD, "has_phone": phone is not None}},
        analysis_version=lead_scoring_service.ANALYSIS_VERSION,
        scored_at=utcnow(),
    )
    db.add_all([session, lead])
    db.commit()
    return user


def test_the_inbox_carries_the_tier_and_the_number_to_dial(client, db_session):
    _waiting_customer(db_session, email="a@example.com", tier=LeadTier.HOT, waited_minutes=1, phone="0912345678")

    entries = client.get("/api/v1/sale/live-inbox").json()

    assert len(entries) == 1
    assert entries[0]["lead_tier"] == "hot"
    assert entries[0]["lead_score"] == 80
    assert entries[0]["customer_phone"] == "0912345678"
    assert entries[0]["customer_label"] == "Khách Thử"
    assert "ngân sách" in entries[0]["lead_reason"]


def test_hot_leads_come_first_when_everyone_has_waited_the_same(client, db_session):
    _waiting_customer(db_session, email="cold@example.com", tier=LeadTier.COLD, waited_minutes=2)
    _waiting_customer(db_session, email="hot@example.com", tier=LeadTier.HOT, waited_minutes=1)
    _waiting_customer(db_session, email="warm@example.com", tier=LeadTier.WARM, waited_minutes=1)

    tiers = [entry["lead_tier"] for entry in client.get("/api/v1/sale/live-inbox").json()]

    assert tiers == ["hot", "warm", "cold"]


def test_a_starved_cold_customer_outranks_a_fresh_hot_one(client, db_session):
    """The fairness escape. Without it, a busy day means the COLD customer is never seen."""
    fairness = get_settings().lead_inbox_fairness_minutes
    _waiting_customer(db_session, email="hot@example.com", tier=LeadTier.HOT, waited_minutes=0)
    _waiting_customer(db_session, email="cold@example.com", tier=LeadTier.COLD, waited_minutes=fairness + 5)

    entries = client.get("/api/v1/sale/live-inbox").json()

    assert entries[0]["lead_tier"] == "cold"
    assert entries[1]["lead_tier"] == "hot"


def test_a_customer_with_no_lead_row_renders_as_cold_rather_than_blank(client, db_session):
    """`lead_tier` is non-nullable so the badge always draws — the alternative is an empty
    pill on the most common row on the page."""
    user = User(username="b@example.com", email="b@example.com", hashed_password="x", role=UserRole.CUSTOMER)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    db_session.add(
        ChatSession(
            customer_id=user.id,
            status=SessionStatus.WAITING_SALE,
            channel=SessionChannel.LIVE,
            handoff_requested_at=utcnow(),
        )
    )
    db_session.commit()

    entry = client.get("/api/v1/sale/live-inbox").json()[0]

    assert entry["lead_tier"] == "cold"
    assert entry["lead_score"] == 0
    assert entry["customer_phone"] is None


def test_the_inbox_recalculates_a_hot_badge_from_an_old_ruleset(client, db_session):
    user = _waiting_customer(
        db_session,
        email="legacy@example.com",
        tier=LeadTier.HOT,
        waited_minutes=1,
        phone="0912345678",
    )
    lead = db_session.query(Lead).filter(Lead.customer_id == user.id).one()
    lead.score = 100
    lead.analysis_version = "rules-1"
    lead.signals = {
        "flags": {
            "registered": True,
            "has_phone": True,
            "stated_budget": True,
            "budget_over_1bn": True,
            "closing_intent": True,
            "wants_human": True,
        }
    }
    db_session.commit()

    entry = client.get("/api/v1/sale/live-inbox").json()[0]

    assert entry["lead_tier"] == "warm"
    assert entry["lead_score"] == 40
    db_session.refresh(lead)
    assert lead.analysis_version == lead_scoring_service.ANALYSIS_VERSION
