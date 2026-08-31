"""Customer registration now captures contact details — the number a Sale actually dials.

`full_name` had been declared on `CustomerRegisterRequest` since the gate shipped but was
never persisted, and no test covered this endpoint at all, so these are the first.
"""

import pytest
from fastapi.testclient import TestClient

from backend.core.config import get_settings
from backend.core.mysql_client import get_db
from backend.core.rate_limit import anonymous_rate_limit
from backend.main import app
from backend.models.user import User
from backend.utils.phone import normalise_vn_mobile


@pytest.fixture
def client(db_session):
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[anonymous_rate_limit] = lambda: None
    yield TestClient(app)
    app.dependency_overrides.clear()


def _register(client: TestClient, **overrides) -> object:
    payload = {
        "email": "khach@example.com",
        "password": "matkhau12345",
        "full_name": "Nguyễn Văn A",
        "phone": "0912345678",
    }
    payload.update(overrides)
    return client.post("/api/v1/customer/register", json=payload)


@pytest.mark.parametrize(
    "typed",
    ["0912345678", "+84912345678", "84912345678", "0912 345 678", "0912.345.678", "(091) 234-5678"],
)
def test_every_way_of_typing_one_number_is_stored_identically(client, db_session, typed):
    """A Sale reading the inbox must not see six spellings of one person's number."""
    response = _register(client, phone=typed)

    assert response.status_code == 201
    user = db_session.query(User).filter(User.email == "khach@example.com").one()
    assert user.phone == "0912345678"
    assert user.full_name == "Nguyễn Văn A"


def test_landline_is_rejected(client):
    """The number exists so a Sale can call the person; 02x does not reach a phone in a pocket."""
    assert _register(client, phone="0212345678").status_code == 422


def test_registration_without_a_phone_is_refused_while_the_gate_requires_one(client):
    assert get_settings().lead_require_phone_on_register is True
    assert _register(client, phone=None).status_code == 422


def test_phone_never_reaches_the_audit_log(client, capture_audit):
    """`audit_logs` rows have no FK and outlive the account they describe.

    A phone number written into the payload therefore survives the user being deleted,
    which is the opposite of what a contact field should do. The event carries the boolean
    `phone_captured` instead — enough to answer "is the gate working?" at no privacy cost.
    """
    assert _register(client).status_code == 201

    emitted = " ".join(str(record.__dict__) for record in capture_audit)
    assert "0912345678" not in emitted
    assert "Nguyễn Văn A" not in emitted
    assert any(record.__dict__.get("phone_captured") is True for record in capture_audit)


def test_normaliser_treats_blank_as_absent_not_invalid():
    """Whether a phone is REQUIRED is policy (a setting), not parsing — so blank is not an error."""
    assert normalise_vn_mobile("") is None
    assert normalise_vn_mobile("   ") is None
    assert normalise_vn_mobile(None) is None
