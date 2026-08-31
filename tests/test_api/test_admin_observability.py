import json

import pytest
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.core.deps import get_current_user
from backend.core.enums import MessageSender, UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.audit_log import AuditLog
from backend.models.chat_session import ChatSession
from backend.models.message import Message
from backend.models.observability import LlmUsageEvent, PipelineTraceRun
from backend.models.user import User
from backend.utils.time import utcnow


@pytest.fixture
def client(db_session):
    admin = User(username="admin-observe", email="admin-observe@example.com", hashed_password="x", role=UserRole.ADMIN)
    customer = User(
        username="observe-customer", email="observe-customer@example.com", hashed_password="x", role=UserRole.CUSTOMER
    )
    db_session.add_all([admin, customer])
    db_session.commit()
    db_session.refresh(admin)
    db_session.refresh(customer)
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app), customer
    app.dependency_overrides.clear()


def test_observability_aggregates_trace_tokens_logs_and_fallbacks(client, db_session, tmp_path, monkeypatch):
    test_client, customer = client
    now = utcnow()
    trace_file = tmp_path / "runs.jsonl"
    trace = {
        "run_id": "trace-123",
        "started_at": now.isoformat(),
        "duration_ms": 245.5,
        "project_id": None,
        "clearance": "public",
        "outcome": "completed",
        "verifier_score": 0.35,
        "steps": [
            {"name": "retrieve", "at_ms": 5, "ok": True, "doc_count": 3, "duration_ms": 40},
            {"name": "llm.usage", "at_ms": 60, "input_tokens": 120, "output_tokens": 45},
            {"name": "verify", "at_ms": 200, "score": 0.35, "duration_ms": 30},
        ],
    }
    trace_file.write_text(json.dumps(trace), encoding="utf-8")
    monkeypatch.setattr(settings, "trace_file", str(trace_file))
    monkeypatch.setattr(settings, "tracing_enabled", True)
    monkeypatch.setattr(settings, "token_input_cost_per_million_usd", 1.0)
    monkeypatch.setattr(settings, "token_output_cost_per_million_usd", 2.0)

    session = ChatSession(customer_id=customer.id)
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    db_session.add_all(
        [
            Message(session_id=session.id, sender=MessageSender.CUSTOMER, content="Tôi cần căn khoảng 4 tỷ"),
            Message(
                session_id=session.id,
                sender=MessageSender.AGENT,
                content="Fallback",
                verifier_score=0.35,
                failure_mode="insufficient_context",
            ),
            AuditLog(event="pipeline.generate.failed", user_id=customer.id, username=customer.username),
        ]
    )
    db_session.commit()

    response = test_client.get("/api/v1/admin/observability?days=14")

    assert response.status_code == 200, response.text
    body = response.json()
    rag = next(row for row in body["tool_reliability"] if row["key"] == "retrieve")
    assert rag["success_rate"] == 100.0
    assert body["tokens"]["input_tokens"] == 120
    assert body["tokens"]["output_tokens"] == 45
    assert body["tokens"]["cost_configured"] is True
    assert body["logs"][0]["severity"] == "ERROR"
    assert body["traces"][0]["run_id"] == "trace-123"
    assert body["fallback_alerts"][0]["severity"] == "critical"
    assert next(row for row in body["budget_intents"] if row["label"] == "3–5 tỷ")["count"] == 1

    trace_response = test_client.get("/api/v1/admin/observability/traces/trace-123")
    assert trace_response.status_code == 200
    assert trace_response.json()["steps"][0]["detail"] == "3 tài liệu"


def test_observability_reads_durable_mysql_traces_and_usage(client, db_session, tmp_path, monkeypatch):
    test_client, _customer = client
    now = utcnow()
    monkeypatch.setattr(settings, "trace_file", str(tmp_path / "missing.jsonl"))
    monkeypatch.setattr(settings, "observability_metrics_enabled", True)

    trace = {
        "run_id": "mysql-trace-1",
        "started_at": now.isoformat(),
        "duration_ms": 125.0,
        "project_id": "ocp1",
        "clearance": "internal",
        "outcome": "answered",
        "verifier_score": 0.92,
        "steps": [
            {"name": "retrieve", "at_ms": 2, "ok": True, "doc_count": 2, "duration_ms": 25},
            {
                "name": "llm.usage",
                "at_ms": 30,
                "usage_id": "usage-1",
                "input_tokens": 300,
                "output_tokens": 80,
            },
        ],
    }
    db_session.add_all(
        [
            PipelineTraceRun(
                run_id="mysql-trace-1",
                started_at=now,
                duration_ms=125.0,
                project_id="ocp1",
                clearance="internal",
                outcome="answered",
                verifier_score=0.92,
                payload=trace,
            ),
            LlmUsageEvent(
                usage_id="usage-1",
                run_id="mysql-trace-1",
                operation="gemini_generation",
                model="gemini-test",
                input_tokens=300,
                output_tokens=80,
                total_tokens=380,
                created_at=now,
            ),
            LlmUsageEvent(
                usage_id="usage-classification",
                operation="gemini_generation",
                model="gemini-test",
                input_tokens=500,
                output_tokens=100,
                total_tokens=600,
                created_at=now,
            ),
        ]
    )
    db_session.commit()

    response = test_client.get("/api/v1/admin/observability?days=14")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tracing_enabled"] is True
    assert body["tokens"]["input_tokens"] == 800
    assert body["tokens"]["output_tokens"] == 180
    assert body["traces"][0]["run_id"] == "mysql-trace-1"
    rag = next(row for row in body["tool_reliability"] if row["key"] == "retrieve")
    assert rag["calls"] == 1
    assert rag["average_latency_ms"] == 25.0

    trace_response = test_client.get("/api/v1/admin/observability/traces/mysql-trace-1")
    assert trace_response.status_code == 200
    assert trace_response.json()["outcome"] == "answered"
