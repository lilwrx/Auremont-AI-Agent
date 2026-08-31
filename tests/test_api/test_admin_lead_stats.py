"""Admin lead aggregates — the two rates that decide whether the feature is working.

`contact_rate` says whether requiring a phone at the gate is actually capturing numbers.
`llm_enrichment.call_rate` makes the cost brake in lead_scoring_service a measured figure
rather than an assumed one.
"""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user
from backend.core.enums import LeadTier, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.lead import Lead
from backend.models.user import User
from backend.utils.time import utcnow


@pytest.fixture
def client(db_session):
    admin = User(username="admin", email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
    db_session.add(admin)
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


def _lead(db, *, tier: LeadTier, phone: str | None, method: str = "rule", days_ago: int = 0, score: int = 50):
    email = f"c{db.query(Lead).count()}{days_ago}@example.com"
    user = User(username=email, email=email, hashed_password="x", role=UserRole.CUSTOMER, phone=phone)
    db.add(user)
    db.commit()
    db.refresh(user)
    db.add(
        Lead(
            customer_id=user.id,
            tier=tier,
            score=score,
            detection_method=method,
            scored_at=utcnow() - timedelta(days=days_ago),
        )
    )
    db.commit()


def test_totals_split_by_tier(client, db_session):
    _lead(db_session, tier=LeadTier.HOT, phone="0912345678")
    _lead(db_session, tier=LeadTier.HOT, phone="0912345679")
    _lead(db_session, tier=LeadTier.WARM, phone=None)
    _lead(db_session, tier=LeadTier.COLD, phone=None)

    totals = client.get("/api/v1/admin/stats/leads?days=14").json()["totals"]

    assert totals == {"hot": 2, "warm": 1, "cold": 1, "total": 4}


def test_contact_rate_counts_only_leads_reachable_by_phone(client, db_session):
    _lead(db_session, tier=LeadTier.HOT, phone="0912345678")
    _lead(db_session, tier=LeadTier.WARM, phone=None)

    body = client.get("/api/v1/admin/stats/leads?days=14").json()

    assert body["contactable"] == 1
    assert body["contact_rate"] == 0.5


def test_call_rate_reports_how_often_the_llm_pass_actually_ran(client, db_session):
    _lead(db_session, tier=LeadTier.WARM, phone=None, method="rule")
    _lead(db_session, tier=LeadTier.WARM, phone=None, method="rule")
    _lead(db_session, tier=LeadTier.WARM, phone=None, method="rule")
    _lead(db_session, tier=LeadTier.WARM, phone=None, method="rule+llm")

    enrichment = client.get("/api/v1/admin/stats/leads?days=14").json()["llm_enrichment"]

    assert enrichment == {"scored": 4, "llm_calls": 1, "call_rate": 0.25}


def test_leads_scored_before_the_window_are_excluded(client, db_session):
    _lead(db_session, tier=LeadTier.HOT, phone="0912345678", days_ago=0)
    _lead(db_session, tier=LeadTier.HOT, phone="0912345679", days_ago=40)

    body = client.get("/api/v1/admin/stats/leads?days=14").json()

    assert body["totals"]["total"] == 1
    assert len(body["trend"]) == 14


def test_an_empty_period_returns_zeroes_rather_than_dividing_by_zero(client):
    body = client.get("/api/v1/admin/stats/leads?days=14").json()

    assert body["totals"]["total"] == 0
    assert body["contact_rate"] == 0.0
    assert body["avg_score"] == 0.0
    assert body["llm_enrichment"]["call_rate"] == 0.0
