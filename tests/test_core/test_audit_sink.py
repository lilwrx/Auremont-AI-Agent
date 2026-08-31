"""The audit trail must survive the request that produced it.

These tests exist because the obvious implementation — write the audit row on the
request's own session — is wrong in two ways that only show up under failure:

* `auth.login.failure` is emitted immediately before `raise HTTPException`. On a
  shared session that row is never committed, so the security events most worth
  keeping are exactly the ones lost.
* Committing on the request's session would also commit whatever half-finished
  business work is pending there.

Both are covered below, and both fail against a shared-session implementation.
"""

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.core import audit_sink
from backend.core.audit import log_event
from backend.core.context import request_id_var
from backend.core.enums import UserRole
from backend.core.mysql_client import Base, get_db
from backend.models.audit_log import AuditLog
from backend.models.user import User


@pytest.fixture
def audit_db(monkeypatch):
    """Point the sink at a throwaway database and hand back a session factory."""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    monkeypatch.setattr(audit_sink, "SessionLocal", factory)

    yield factory

    Base.metadata.drop_all(bind=engine)


def rows(factory) -> list[AuditLog]:
    session = factory()
    try:
        return session.query(AuditLog).order_by(AuditLog.id).all()
    finally:
        session.close()


class TestPersistence:
    def test_an_event_becomes_a_row(self, audit_db):
        log_event("auth.login.success", username="sale_a", user_id=3, role=UserRole.SALE)

        (row,) = rows(audit_db)
        assert row.event == "auth.login.success"
        assert row.user_id == 3
        assert row.username == "sale_a"

    def test_non_column_fields_land_in_the_payload(self, audit_db):
        log_event("sale.query", user_id=3, verifier_score=0.91, requires_hitl=True)

        (row,) = rows(audit_db)
        assert row.payload == {"verifier_score": 0.91, "requires_hitl": True}
        assert "user_id" not in row.payload

    def test_the_request_id_ties_the_row_to_its_stdout_lines(self, audit_db):
        token = request_id_var.set("corr-77")
        try:
            log_event("auth.logout", user_id=1)
        finally:
            request_id_var.reset(token)

        assert rows(audit_db)[0].request_id == "corr-77"

    def test_an_over_long_username_does_not_abort_the_write(self, audit_db):
        log_event("auth.login.failure", username="x" * 500, reason="bad_credentials")

        (row,) = rows(audit_db)
        assert len(row.username) == 50

    def test_an_unserialisable_value_does_not_cost_the_event(self, audit_db):
        class Hostile:
            def __repr__(self):
                raise RuntimeError("nope")

        log_event("weird.event", obj=Hostile(), ok=1)

        (row,) = rows(audit_db)
        assert row.payload["ok"] == 1
        assert row.payload["obj"] == "<unrepresentable>"

    def test_a_database_outage_never_breaks_the_caller(self, monkeypatch):
        def explode():
            raise RuntimeError("mysql is down")

        monkeypatch.setattr(audit_sink, "SessionLocal", explode)

        log_event("auth.login.success", user_id=1)

    def test_no_database_configured_is_not_an_error(self, monkeypatch):
        monkeypatch.setattr(audit_sink, "SessionLocal", None)

        log_event("auth.login.success", user_id=1)


class TestTransactionIndependence:
    """The two properties that force a separate session."""

    @pytest.fixture
    def app_client(self, audit_db):
        app = FastAPI()

        @app.post("/login-fail")
        def login_fail(db: Session = Depends(get_db)):
            log_event("auth.login.failure", username="attacker", reason="bad_credentials")
            raise HTTPException(status_code=401, detail="Incorrect username or password")

        @app.post("/half-done")
        def half_done(db: Session = Depends(get_db)):
            db.add(User(username="pending", email="p@example.com", hashed_password="x", role=UserRole.SALE))
            log_event("document.upload", document_id=1)
            raise HTTPException(status_code=500, detail="ingest failed")

        def override_get_db():
            session = audit_db()
            try:
                yield session
            finally:
                session.close()

        app.dependency_overrides[get_db] = override_get_db
        return TestClient(app, raise_server_exceptions=False)

    def test_the_event_survives_a_request_that_raises(self, app_client, audit_db):
        response = app_client.post("/login-fail")

        assert response.status_code == 401
        assert [r.event for r in rows(audit_db)] == ["auth.login.failure"]

    def test_writing_an_event_does_not_commit_pending_business_work(self, app_client, audit_db):
        app_client.post("/half-done")

        session = audit_db()
        try:
            assert session.query(User).count() == 0, "audit commit leaked an unrelated pending row"
        finally:
            session.close()
        assert [r.event for r in rows(audit_db)] == ["document.upload"]


class TestSecrets:
    def test_a_login_failure_row_never_holds_a_password(self, audit_db):
        log_event("auth.login.failure", username="victim", reason="bad_credentials")

        (row,) = rows(audit_db)
        assert "password" not in str(row.payload).lower()
        assert row.payload == {"reason": "bad_credentials"}

    def test_hitl_stores_the_shape_of_the_content_not_the_content(self, audit_db):
        """The confirmed text is the price/commitment going to a customer."""
        secret = "Giá căn 2PN là 3.2 tỷ, cam kết giữ giá tới 30/9"

        log_event("hitl.confirm", message_id=5, user_id=1, content_len=len(secret), edited=True)

        (row,) = rows(audit_db)
        assert secret not in str(row.payload)
        assert row.payload["content_len"] == len(secret)
