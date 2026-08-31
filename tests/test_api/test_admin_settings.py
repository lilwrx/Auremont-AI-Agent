"""The Verifier threshold is readable but not editable at runtime.

The PUT used to answer 200 with the submitted value while storing nothing, so the Admin UI
showed "Đã lưu" for a change that never happened — on the one setting that decides when the
AI refuses to answer. Reporting success for a no-op is the bug; these pin the honest answer.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.core.deps import get_current_user
from backend.core.enums import UserRole
from backend.main import app
from backend.models.user import User


@pytest.fixture
def as_admin():
    admin = User(id=1, username="admin", email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)
    app.dependency_overrides[get_current_user] = lambda: admin
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_current_threshold_is_readable(as_admin):
    response = as_admin.get("/api/v1/admin/settings")

    assert response.status_code == 200, response.text
    assert response.json()["verifier_threshold_sale"] == get_settings().verifier_threshold_sale


def test_updating_the_threshold_reports_that_it_is_not_supported(as_admin):
    response = as_admin.put("/api/v1/admin/settings", json={"verifier_threshold_sale": 0.1})

    assert response.status_code == 501


def test_a_rejected_update_leaves_the_threshold_untouched(as_admin):
    """The point of failing loudly: the value the pipeline reads must not have moved."""
    before = get_settings().verifier_threshold_sale

    as_admin.put("/api/v1/admin/settings", json={"verifier_threshold_sale": 0.1})

    assert get_settings().verifier_threshold_sale == before
    assert as_admin.get("/api/v1/admin/settings").json()["verifier_threshold_sale"] == before
