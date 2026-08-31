"""WHERE lead scoring runs — the part that is easy to get wrong and impossible to notice.

`customer_chat.ask_in_customer_session` has four exits, and two of them return before the
agent pipeline is ever reached: the anonymous turn-limit gate (canned copy, no LLM) and a
customer messaging while a Sale already has them. Those are the two turns a lead is hottest
on, and the second is exactly the population the live inbox displays. A hook placed at the
end of the branch chain — or inside the pipeline graph — would score neither, and nothing
would look broken.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.core.deps import get_current_user, get_optional_current_user
from backend.core.enums import LeadTier, SessionChannel, SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.core.rate_limit import anonymous_rate_limit
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.lead import Lead
from backend.models.user import User
from backend.services import agent_pipeline, lead_service
from backend.services.agent_pipeline import PipelineResult

QUALIFIED_MESSAGE = "cho mình xin bảng giá căn 2PN, ngân sách tầm 3.5 tỷ"


@pytest.fixture(autouse=True)
def stub_pipeline(monkeypatch):
    monkeypatch.setattr(
        agent_pipeline,
        "run_pipeline",
        lambda query, project_id=None, db=None, clearance=None, history=None, **_kwargs: PipelineResult(
            draft_answer=f"Trả lời cho: {query}",
            citations=[],
            verifier_score=0.9,
            requires_hitl=False,
        ),
    )


@pytest.fixture
def anonymous_client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.dependency_overrides[anonymous_rate_limit] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def customer(db_session):
    user = User(username="c@example.com", email="c@example.com", hashed_password="x", role=UserRole.CUSTOMER)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def customer_client(db_session, customer):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: customer
    app.dependency_overrides[get_optional_current_user] = lambda: customer
    app.dependency_overrides[anonymous_rate_limit] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def _start_anonymous(client: TestClient) -> tuple[int, str]:
    response = client.post("/api/v1/customer/sessions/anonymous")
    assert response.status_code == 201
    body = response.json()
    return body["session_id"], body["visitor_token"]


def _ask(client: TestClient, session_id: int, token: str, content: str):
    return client.post(
        f"/api/v1/customer/sessions/{session_id}/messages",
        json={"content": content},
        headers={"X-Visitor-Token": token},
    )


def test_the_turn_limit_gated_turn_is_still_scored(anonymous_client, db_session):
    """The gate spends no LLM call and returns canned copy — but it is the turn where an
    anonymous visitor has asked four questions, which is when they matter most."""
    limit = get_settings().customer_anonymous_turn_limit
    session_id, token = _start_anonymous(anonymous_client)

    for _ in range(limit):
        assert _ask(anonymous_client, session_id, token, "còn căn 2PN nào không ạ").status_code == 201

    gated = _ask(anonymous_client, session_id, token, QUALIFIED_MESSAGE)

    assert gated.status_code == 201
    assert gated.json()["gate"] == "turn_limit"
    lead = db_session.query(Lead).filter(Lead.visitor_token == token).one()
    assert lead.turn_count == limit + 1
    assert lead.signals["flags"]["stated_budget"] is True


def test_a_customer_turn_during_a_live_handoff_is_still_scored(customer_client, db_session, customer):
    """The `status != BOT_HANDLING` branch returns None before the pipeline.

    These are the sessions a Sale is looking at in the live inbox, so a hook that missed
    them would leave every badge frozen at whatever it was before the handoff.
    """
    session = ChatSession(customer_id=customer.id, status=SessionStatus.SALE_HANDLING, channel=SessionChannel.LIVE)
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    response = customer_client.post(
        f"/api/v1/customer/sessions/{session.id}/messages", json={"content": QUALIFIED_MESSAGE}
    )

    assert response.status_code == 201
    lead = db_session.query(Lead).filter(Lead.customer_id == customer.id).one()
    assert lead.signals["flags"]["stated_budget"] is True
    assert lead.tier in {LeadTier.WARM, LeadTier.HOT}


def test_a_scoring_failure_never_costs_the_customer_their_answer(anonymous_client, db_session, monkeypatch):
    """A ranking hint must not be able to turn a working answer into a 500."""

    def _boom(*_args, **_kwargs):
        raise RuntimeError("scoring exploded")

    monkeypatch.setattr(lead_service, "_rescore", _boom)
    session_id, token = _start_anonymous(anonymous_client)

    response = _ask(anonymous_client, session_id, token, QUALIFIED_MESSAGE)

    assert response.status_code == 201
    assert response.json()["content"]


def test_a_browsing_visitor_stays_cold(anonymous_client, db_session):
    session_id, token = _start_anonymous(anonymous_client)

    _ask(anonymous_client, session_id, token, "dự án ở đâu ạ")

    lead = db_session.query(Lead).filter(Lead.visitor_token == token).one()
    assert lead.tier == LeadTier.COLD


def test_registering_carries_the_anonymous_score_onto_the_account(anonymous_client, db_session):
    """The visitor's accumulated signals must survive signup, or the gate destroys exactly
    the evidence it was placed there to collect."""
    session_id, token = _start_anonymous(anonymous_client)
    _ask(anonymous_client, session_id, token, QUALIFIED_MESSAGE)
    before = db_session.query(Lead).filter(Lead.visitor_token == token).one().score
    assert before > 0

    response = anonymous_client.post(
        "/api/v1/customer/register",
        json={
            "email": "moi@example.com",
            "password": "matkhau12345",
            "full_name": "Trần B",
            "phone": "0987654321",
            "session_id": session_id,
            "visitor_token": token,
        },
    )

    assert response.status_code == 201
    user = db_session.query(User).filter(User.email == "moi@example.com").one()
    lead = db_session.query(Lead).filter(Lead.customer_id == user.id).one()
    assert lead.visitor_token is None
    assert lead.score >= before
    assert db_session.query(Lead).filter(Lead.visitor_token == token).first() is None
    assert lead.signals["flags"]["has_phone"] is True
    assert lead.tier == LeadTier.WARM
