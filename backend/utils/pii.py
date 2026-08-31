"""Redact personal data out of text before it is written somewhere durable.

`backend/core/audit.py` states the rule — a customer's contact details must never reach the
audit trail — and until now the rule was kept by hand at each call site. That held while
only `sale_chat.py` logged free text, which is a Sale typing about a customer. It stopped
holding when `customer_chat.py` began logging `query` under the same `log_query_text` flag:
that text is the customer's own, and a customer answering "gọi tôi 0912345678" writes their
number into `audit_logs.payload` — a table deliberately created without a foreign key, so
the row outlives the account it describes. Deleting the user does not delete the number.

Redacting here rather than at each call site makes the rule a property of the sink instead
of something every future logging line has to remember.

Deliberately *not* a general PII detector. Each pattern below is a shape that appears in
this product's chat and is unambiguous enough to match without a model: a Vietnamese mobile
number, a citizen ID, an email. Names are not attempted — Vietnamese given names collide
with ordinary words ("Chi", "Hoa", "Tu", "Anh"), so a name matcher would either miss most
names or redact half of every sentence, and a half-working redactor is worse than a stated
boundary because it invites trust it cannot carry.

Scope: text going to logs, traces and the audit table. This is **not** applied to a
customer's message on its way to the model or to the Sale, both of which need the real
number to do their job — `leads` stores it deliberately, as the record the Sale calls back.
"""

import re

_PHONE = re.compile(
    r"(?<!\d)(?:\+?84|0)[\s.\-]?[35789](?:[\s.\-]?\d){8}(?!\d)",
)

_CITIZEN_ID = re.compile(r"(?<!\d)\d{12}(?!\d)|(?<!\d)\d{9}(?!\d)")

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_REPLACEMENTS = (
    (_EMAIL, "[EMAIL]"),
    (_PHONE, "[PHONE]"),
    (_CITIZEN_ID, "[ID]"),
)


def redact_pii(text: str | None) -> str | None:
    """Replace contact details in `text` with labels. `None` and empty pass through.

    Order matters between the patterns; see `_REPLACEMENTS`.
    """
    if not text:
        return text

    for pattern, replacement in _REPLACEMENTS:
        text = pattern.sub(replacement, text)
    return text
