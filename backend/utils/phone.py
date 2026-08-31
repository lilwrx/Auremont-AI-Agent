"""Vietnamese mobile number normalisation, so one number has one stored form.

Every path that accepts a phone number goes through `normalise_vn_mobile`. Without a single
normaliser, "0912 345 678", "+84912345678" and "0912.345.678" become three different rows
describing one person, and the Sale calling from the live inbox sees whichever the visitor
happened to type.
"""

import re

_VN_MOBILE = re.compile(r"^0[35789]\d{8}$")

_SEPARATORS = re.compile(r"[\s.\-()]+")


def normalise_vn_mobile(raw: str | None) -> str | None:
    """Return the number as `0xxxxxxxxx`, or None when nothing was supplied.

    Raises ValueError when a non-empty value cannot be read as a Vietnamese mobile number,
    so callers can surface it as a validation error rather than storing something a Sale
    will later fail to dial. Empty input is NOT an error: whether a phone number is required
    is a policy decision (`lead_require_phone_on_register`), not a parsing one.
    """
    if raw is None:
        return None

    digits = _SEPARATORS.sub("", raw.strip())
    if not digits:
        return None

    if digits.startswith("+84"):
        digits = "0" + digits[3:]
    elif digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]

    if not _VN_MOBILE.match(digits):
        raise ValueError("Số điện thoại không hợp lệ (VD: 0912345678)")
    return digits
