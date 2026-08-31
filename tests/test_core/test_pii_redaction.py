"""Contact details must not reach the audit trail, whoever typed them.

`audit_logs` is deliberately created without a foreign key so its rows outlive the user they
describe (see `backend/core/audit.py`). A phone number written there is therefore not
removed by deleting the account, which is what makes this a data-retention problem rather
than a tidiness one.

The other half of these tests is the false positives. A redactor that eats prices, areas or
unit codes would quietly destroy the field that exists to reproduce a wrong answer, and
nobody would notice until they needed it.
"""

import asyncio
from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from backend.core.audit import redact_and_truncate, truncate
from backend.utils.phone import normalise_vn_mobile
from backend.utils.pii import redact_pii


@dataclass
class _RegisterPayload:
    """Just the fields `register_customer` reads before it raises."""

    email: str
    password: str
    full_name: str
    phone: str | None = None
    session_id: int | None = None
    visitor_token: str | None = None


@pytest.mark.parametrize(
    "written",
    [
        "0912345678",
        "0912 345 678",
        "0912.345.678",
        "0912-345-678",
        "+84912345678",
        "84912345678",
        "0387654321",
        "0587654321",
        "0787654321",
        "0887654321",
    ],
)
def test_a_phone_number_never_reaches_the_trail(written):
    """People type their number every way there is; the row outlives them either way."""
    assert written not in redact_pii(f"gọi tôi {written} nhé")
    assert "[PHONE]" in redact_pii(f"gọi tôi {written} nhé")


def test_citizen_id_and_email_are_redacted():
    redacted = redact_pii("CCCD 001234567890, mail an@vinhomes.vn, CMND cũ 012345678")

    assert "001234567890" not in redacted
    assert "an@vinhomes.vn" not in redacted
    assert "012345678" not in redacted
    assert "[ID]" in redacted and "[EMAIL]" in redacted


def test_an_email_survives_as_one_piece():
    """Emails are matched first: an address containing a digit run would otherwise be
    half-eaten by the ID pattern, leaving a mangled fragment in the log."""
    assert redact_pii("gửi tới a123456789@vin.vn") == "gửi tới [EMAIL]"


@pytest.mark.parametrize(
    "kept",
    [
        "căn 2PN giá 3,6 tỷ đồng",
        "diện tích 68,2 m²",
        "chiết khấu 5% khi thanh toán sớm",
        "thanh toán theo tiến độ 8 đợt",
        "mã căn OP3-BE1-1205",
        "hotline 02439743333",
    ],
)
def test_business_figures_are_left_alone(kept):
    """Over-redaction is its own failure: the query field exists to reproduce a wrong
    answer, and a redactor that eats prices destroys exactly that."""
    assert redact_pii(kept) == kept


def test_redaction_happens_before_truncation():
    """Truncating first would cut a number in half, and eight digits of somebody's number
    is still their number sitting in a table with no foreign key."""
    text = "x" * 195 + " 0912345678"

    assert "0912345678" not in (redact_and_truncate(text) or "")
    assert "345678" not in (redact_and_truncate(text) or "")


def test_plain_truncate_still_shows_the_sale_a_number():
    """`truncate` also builds the Sale's inbox preview, where the customer's number is
    precisely what the Sale needs in order to call them back."""
    assert "0912345678" in (truncate("gọi tôi 0912345678") or "")


def test_redaction_agrees_with_the_normaliser_on_what_a_number_is():
    """`phone.py` decides what is storable and this decides what is hideable. If they drift,
    a number good enough to store is one the trail would keep in the clear."""
    for written in ("0912345678", "+84912345678", "0912 345 678"):
        assert normalise_vn_mobile(written) == "0912345678"
        assert "[PHONE]" in redact_pii(written)


def test_empty_and_none_pass_through():
    assert redact_pii(None) is None
    assert redact_pii("") == ""
    assert redact_and_truncate(None) is None


def test_a_failed_registration_records_no_email(monkeypatch):
    """The redactor is a backstop for free text; it cannot see a contact detail passed as
    its own field. `customer.register.failure` fires when no account is created, so the
    address would be a stranger's, kept forever in a table with no foreign key to delete it
    by — and `reason` already answers the only question asked of the event.

    Contrast `auth.login.failure`, which logs a username on purpose: staff account, and a
    security trail is what it is for.
    """
    import backend.routers.customer_chat as customer_chat

    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(customer_chat, "log_event", lambda event, **fields: events.append((event, fields)))
    monkeypatch.setattr(customer_chat, "get_user_by_email", lambda _db, _email: object())

    with pytest.raises(HTTPException):
        asyncio.run(
            customer_chat.register_customer(
                _RegisterPayload(email="someone@example.com", password="x", full_name="A"),
                db=None,
            )
        )

    assert events, "the failure was not audited at all"
    for _event, fields in events:
        assert "someone@example.com" not in str(fields), fields
        assert fields.get("reason") == "email_taken"
