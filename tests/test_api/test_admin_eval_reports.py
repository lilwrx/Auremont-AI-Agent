import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.core.config import settings
from backend.core.deps import get_current_user
from backend.core.enums import UserRole
from backend.core.mysql_client import get_db
from backend.main import app
from backend.models.user import User


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def order_by(self, *_args):
        return self

    def limit(self, _limit):
        return self

    def all(self):
        return self.rows


class _FakeDb:
    rows = []

    def query(self, *_args):
        return _FakeQuery(self.rows)


@pytest.fixture
def fake_db():
    return _FakeDb()


@pytest.fixture
def as_admin(fake_db):
    admin = User(id=1, username="admin-eval", email="admin-eval@example.com", hashed_password="x", role=UserRole.ADMIN)
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_db] = lambda: fake_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_eval_reports_return_both_artifacts_without_raw_case_details(as_admin, tmp_path, monkeypatch):
    deepeval_path = tmp_path / "deepeval_report.json"
    evaluation_path = tmp_path / "report.json"
    deepeval_path.write_text(
        json.dumps(
            {
                "cases": 2,
                "runs": 3,
                "passed": 2,
                "failed": 1,
                "pass_rate": 0.6667,
                "complete": True,
                "answer_model": "answer-model",
                "judge_model": "judge-model",
                "independent_judge": True,
                "deterministic_metrics": ["Required Facts"],
                "metrics": {
                    "Faithfulness": {
                        "total": 3,
                        "passed": 2,
                        "failed": 1,
                        "mean_score": 0.81,
                        "examples": ["Unsupported claim"],
                    }
                },
                "per_case": {"pricing-policy": {"attempts": 2, "passed": 1, "pass_rate": 0.5, "flaky": True}},
                "flaky_cases": ["pricing-policy"],
                "cases_detail": [{"input": "private question", "answer": "private answer"}],
            }
        ),
        encoding="utf-8",
    )
    evaluation_path.write_text(
        json.dumps(
            {
                "runs": 4,
                "passed": 3,
                "failed": 1,
                "pass_rate": 0.75,
                "outcomes": {"answered": 4},
                "failure_modes": {"missing-evidence": 1},
                "graders": {
                    "answered_runs_are_grounded": {
                        "total": 4,
                        "passed": 3,
                        "failed": 1,
                        "examples": ["Answered with no citations."],
                    }
                },
                "latency_ms": {"p50": 900, "p95": 2400, "max": 3100},
                "retries": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "deepeval_report_path", str(deepeval_path))
    monkeypatch.setattr(settings, "evaluation_report_path", str(evaluation_path))

    response = as_admin.get("/api/v1/admin/eval/reports")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deepeval"]["status"] == "ready"
    assert body["deepeval"]["source"] == "artifact"
    assert body["deepeval"]["report"]["metrics"]["Faithfulness"]["mean_score"] == 0.81
    assert "cases_detail" not in body["deepeval"]["report"]
    assert body["evaluation"]["status"] == "ready"
    assert body["evaluation"]["source"] == "artifact"
    assert body["evaluation"]["report"]["latency_ms"]["p95"] == 2400
    assert body["deepeval"]["generated_at"] is not None


def test_eval_reports_describe_missing_and_invalid_artifacts(as_admin, tmp_path, monkeypatch):
    invalid_path = tmp_path / "deepeval_report.json"
    invalid_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(settings, "deepeval_report_path", str(invalid_path))
    monkeypatch.setattr(settings, "evaluation_report_path", str(tmp_path / "missing.json"))

    response = as_admin.get("/api/v1/admin/eval/reports")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["deepeval"]["status"] == "invalid"
    assert body["deepeval"]["report"] is None
    assert body["evaluation"]["status"] == "missing"
    assert body["evaluation"]["report"] is None


def test_pipeline_evaluation_falls_back_to_durable_traces(as_admin, fake_db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "deepeval_report_path", str(tmp_path / "missing-deep.json"))
    monkeypatch.setattr(settings, "evaluation_report_path", str(tmp_path / "missing-eval.json"))
    fake_db.rows = [
        SimpleNamespace(
            started_at=datetime(2026, 8, 29, 8, 0, tzinfo=UTC),
            payload={
                "run_id": "run-1",
                "duration_ms": 1200,
                "outcome": "answered",
                "citation_count": 1,
                "steps": [],
            },
        )
    ]

    response = as_admin.get("/api/v1/admin/eval/reports")

    assert response.status_code == 200, response.text
    evaluation = response.json()["evaluation"]
    assert evaluation["status"] == "ready"
    assert evaluation["source"] == "live_traces"
    assert evaluation["report"]["runs"] == 1
    assert evaluation["report"]["pass_rate"] == 1.0


def test_eval_reports_require_admin(client):
    response = client.get("/api/v1/admin/eval/reports")

    assert response.status_code == 401
