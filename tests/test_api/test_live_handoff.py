"""AI -> Sale live handoff: claim race safety, ownership isolation from `sale_chat.py`,
and the customer_chat status branching (AI stays silent once a Sale is involved).
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.deps import get_current_user, get_optional_current_user
from backend.core.enums import MessageSender, SessionChannel, SessionStatus, UserRole
from backend.core.mysql_client import get_db
from backend.core.rate_limit import anonymous_rate_limit
from backend.main import app
from backend.models.chat_session import ChatSession
from backend.models.user import User
from backend.repositories.chat_session import (
    claim_for_sale,
    enter_waiting_queue,
    get_or_create_live_session,
    list_sessions_for_sale,
)
from backend.repositories.message import create_message
from backend.schemas.customer_summary import CustomerNeeds, CustomerSummaryMetadata, CustomerSummarySnapshot
from backend.services import agent_pipeline, customer_summary_service
from backend.services.agent_pipeline import PipelineResult


@pytest.fixture
def sale(db_session):
    user = User(username="sale_a", email="sale_a@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def other_sale(db_session):
    user = User(username="sale_b", email="sale_b@example.com", hashed_password="x", role=UserRole.SALE)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def customer(db_session):
    user = User(username="cust@example.com", email="cust@example.com", hashed_password="x", role=UserRole.CUSTOMER)
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture
def as_sale(db_session):
    def _login(user: User) -> TestClient:
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        return TestClient(app)

    yield _login
    app.dependency_overrides.clear()


@pytest.fixture
def as_customer(db_session):
    """`customer_chat.py`'s dual-auth endpoints depend on `get_optional_current_user`, while
    the CUSTOMER-only ones (require_role) resolve through `get_current_user` — override both
    so a logged-in customer works across every endpoint in this router."""

    def _login(user: User) -> TestClient:
        app.dependency_overrides[get_db] = lambda: db_session
        app.dependency_overrides[get_current_user] = lambda: user
        app.dependency_overrides[get_optional_current_user] = lambda: user
        return TestClient(app)

    yield _login
    app.dependency_overrides.clear()


@pytest.fixture
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


def test_claim_for_sale_is_race_safe(db_session, customer):
    session = get_or_create_live_session(db_session, customer_id=customer.id)
    session.status = SessionStatus.WAITING_SALE
    db_session.commit()

    first = claim_for_sale(db_session, session.id, sale_id=1)
    second = claim_for_sale(db_session, session.id, sale_id=2)

    assert first is not None
    assert first.sale_id == 1
    assert first.status == SessionStatus.SALE_HANDLING
    assert second is None


def test_waiting_time_is_measured_from_the_handoff_not_session_creation(db_session, sale, customer):
    """Regression: a session can sit around for a long time chatting with the AI before it
    ever needs a human — the live-inbox "waiting since" must reflect the moment it actually
    entered the queue (`handoff_requested_at`), not the session's original `created_at`.
    """
    from datetime import datetime, timedelta

    from backend.utils.time import utcnow

    session = get_or_create_live_session(db_session, customer_id=customer.id)
    session.created_at = utcnow() - timedelta(hours=11)
    db_session.commit()

    enter_waiting_queue(db_session, session)

    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: sale
    client = TestClient(app)
    try:
        entry = client.get("/api/v1/sale/live-inbox").json()[0]
        waiting_since = datetime.fromisoformat(entry["waiting_since"])
        assert (utcnow() - waiting_since) < timedelta(minutes=1)
    finally:
        app.dependency_overrides.clear()


def test_claimed_customer_session_excluded_from_sale_self_consult_list(db_session, sale, customer):
    session = get_or_create_live_session(db_session, customer_id=customer.id)
    session.status = SessionStatus.WAITING_SALE
    db_session.commit()
    claim_for_sale(db_session, session.id, sale_id=sale.id)

    assert list_sessions_for_sale(db_session, sale_id=sale.id) == []


def test_sale_chat_rejects_a_claimed_customer_session(as_sale, sale, db_session, customer):
    """`sale_chat.py`'s AI-consult endpoint must 404 on a session it doesn't own the normal
    way, even though `sale_id` matches after a claim — routing through it would call the AI
    pipeline mid-handoff. See `_owned_session`'s updated guard in routers/sale_chat.py."""
    session = get_or_create_live_session(db_session, customer_id=customer.id)
    session.status = SessionStatus.WAITING_SALE
    db_session.commit()
    claim_for_sale(db_session, session.id, sale_id=sale.id)

    client = as_sale(sale)
    assert client.get(f"/api/v1/sale/sessions/{session.id}/messages").status_code == 404
    assert client.delete(f"/api/v1/sale/sessions/{session.id}").status_code == 404


def test_full_handoff_flow(as_customer, as_sale, sale, other_sale, customer, stub_pipeline):
    """The AI thread and the live-Sale thread are separate sessions: asking for a human
    queues the live one, and the Sale only ever sees that one."""
    customer_client = as_customer(customer)

    ai_session_id = customer_client.post("/api/v1/customer/sessions", json={}).json()["id"]

    customer_client.post(
        f"/api/v1/customer/sessions/{ai_session_id}/messages", json={"content": "Ngân sách của tôi là 2 tỷ"}
    )

    handoff = customer_client.post(
        f"/api/v1/customer/sessions/{ai_session_id}/messages",
        json={"content": "Tôi muốn gặp chuyên viên tư vấn"},
    )
    assert handoff.status_code == 201, handoff.text
    body = handoff.json()
    assert body["status"] == "waiting_sale"
    assert body["sender"] == "agent"

    live_session_id = customer_client.get("/api/v1/customer/sessions/live").json()["id"]
    assert live_session_id != ai_session_id

    sale_a_client = as_sale(sale)
    inbox = sale_a_client.get("/api/v1/sale/live-inbox").json()
    assert [row["session_id"] for row in inbox] == [live_session_id]

    claimed = sale_a_client.post(f"/api/v1/sale/live-inbox/{live_session_id}/claim")
    assert claimed.status_code == 200, claimed.text

    sale_b_client = as_sale(other_sale)
    assert sale_b_client.post(f"/api/v1/sale/live-inbox/{live_session_id}/claim").status_code == 409

    sale_a_client = as_sale(sale)

    assert sale_a_client.get("/api/v1/sale/live-inbox").json() == []
    mine = sale_a_client.get("/api/v1/sale/live-inbox/mine").json()
    assert [row["session_id"] for row in mine] == [live_session_id]

    assert sale_a_client.get(f"/api/v1/sale/live-inbox/{ai_session_id}/messages").status_code == 404
    assert sale_a_client.post(f"/api/v1/sale/live-inbox/{ai_session_id}/claim").status_code in (404, 409)

    live_history = sale_a_client.get(f"/api/v1/sale/live-inbox/{live_session_id}/messages").json()
    assert all("Ngân sách" not in m["content"] for m in live_history)

    reply = sale_a_client.post(
        f"/api/v1/sale/live-inbox/{live_session_id}/reply", json={"content": "Chào anh/chị, em là Sale hỗ trợ ạ."}
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["sender"] == "sale"

    status_check = customer_client.get(f"/api/v1/customer/sessions/{live_session_id}")
    assert status_check.json()["status"] == "sale_handling"
    messages = customer_client.get(f"/api/v1/customer/sessions/{live_session_id}/messages").json()
    assert any("Chào anh/chị" in m["content"] for m in messages)

    after_reply = customer_client.post(
        f"/api/v1/customer/sessions/{live_session_id}/messages", json={"content": "Dạ em cảm ơn"}
    )
    assert after_reply.json() is None

    still_ai = customer_client.post(
        f"/api/v1/customer/sessions/{ai_session_id}/messages", json={"content": "Dự án có tiện ích gì?"}
    )
    assert still_ai.json() is not None
    assert still_ai.json()["status"] == "bot_handling"

    ended = sale_a_client.post(f"/api/v1/sale/live-inbox/{live_session_id}/end")
    assert ended.status_code == 201, ended.text
    assert sale_a_client.get("/api/v1/sale/live-inbox/mine").json() == []

    status_after_end = customer_client.get(f"/api/v1/customer/sessions/{live_session_id}")
    assert status_after_end.json()["status"] == "bot_handling"


def test_customer_can_self_service_return_to_ai_while_waiting(as_customer, customer, db_session):
    """A customer stuck in WAITING_SALE (no Sale has claimed them yet) must have their own
    way back to the AI — not just an option the Sale controls."""
    client = as_customer(customer)
    session_id = client.post("/api/v1/customer/sessions", json={}).json()["id"]

    handoff = client.post(f"/api/v1/customer/sessions/{session_id}/request-human")
    assert handoff.json()["status"] == "waiting_sale"

    returned = client.post(f"/api/v1/customer/sessions/{session_id}/return-to-ai")
    assert returned.status_code == 201, returned.text
    assert returned.json()["status"] == "bot_handling"

    status_check = client.get(f"/api/v1/customer/sessions/{session_id}")
    assert status_check.json()["status"] == "bot_handling"


def test_anonymous_visitor_asking_for_a_human_stays_in_self_service(db_session, stub_pipeline):
    """An anonymous visitor can ask the AI about Sale contact without a registration wall."""
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[anonymous_rate_limit] = lambda: None
    client = TestClient(app)
    try:
        anon = client.post("/api/v1/customer/sessions/anonymous").json()
        headers = {"X-Visitor-Token": anon["visitor_token"]}

        response = client.post(
            f"/api/v1/customer/sessions/{anon['session_id']}/messages",
            json={"content": "Cho em gặp người thật với"},
            headers=headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["gate"] is None
        assert body["status"] == "bot_handling"
    finally:
        app.dependency_overrides.clear()


def _claimed_live_session(db, sale, customer, question: str):
    """A session a Sale has taken over, holding one customer question to answer."""
    session = get_or_create_live_session(db, customer_id=customer.id)
    enter_waiting_queue(db, session)
    claim_for_sale(db, session.id, sale_id=sale.id)
    create_message(db, session.id, sender=MessageSender.CUSTOMER, content=question)
    return session


def test_only_assigned_sale_can_refresh_the_cross_channel_customer_summary(
    as_sale, sale, other_sale, customer, db_session, monkeypatch
):
    ai_session = ChatSession(customer_id=customer.id, channel=SessionChannel.AI)
    db_session.add(ai_session)
    db_session.commit()
    db_session.refresh(ai_session)
    create_message(
        db_session,
        ai_session.id,
        sender=MessageSender.CUSTOMER,
        content="Ngân sách của tôi là 3 tỷ.",
    )
    live_session = _claimed_live_session(db_session, sale, customer, "Tôi muốn xem căn 2PN.")

    monkeypatch.setattr(
        customer_summary_service,
        "generate_json",
        lambda *_args, **_kwargs: CustomerSummarySnapshot(
            summary_text="Khách tìm căn 2PN với ngân sách 3 tỷ.",
            metadata=CustomerSummaryMetadata(needs=CustomerNeeds(unit_types=["2PN"], budget_max=3_000_000_000)),
        ),
    )

    response = as_sale(sale).post(f"/api/v1/sale/live-inbox/{live_session.id}/customer-summary/refresh")
    assert response.status_code == 200, response.text
    assert response.json()["source_message_count"] == 2
    assert response.json()["newly_processed_message_count"] == 2

    forbidden = as_sale(other_sale).post(f"/api/v1/sale/live-inbox/{live_session.id}/customer-summary/refresh")
    assert forbidden.status_code == 404


@pytest.mark.parametrize("risky", [True, False])
def test_suggest_reports_whether_the_draft_carries_commitment_risk(
    as_sale, sale, customer, db_session, monkeypatch, risky
):
    """Replies on this screen reach the customer directly, with no HITL card in between,
    so the Sale UI needs to know when the co-pilot drafted a price/commitment answer.
    Dropping the flag here left an AI-authored commitment one Enter away from the customer.
    """
    monkeypatch.setattr(
        agent_pipeline,
        "run_pipeline",
        lambda query, project_id=None, db=None, clearance=None, history=None, **_kwargs: PipelineResult(
            draft_answer="Giá căn 2PN là 3,6 tỷ đồng.",
            citations=[],
            verifier_score=0.9,
            requires_hitl=risky,
        ),
    )
    session = _claimed_live_session(db_session, sale, customer, "Giá căn 2PN?")

    response = as_sale(sale).post(f"/api/v1/sale/live-inbox/{session.id}/suggest")

    assert response.status_code == 200, response.text
    assert response.json()["requires_hitl"] is risky
    assert response.json()["draft"] == "Giá căn 2PN là 3,6 tỷ đồng."
