"""One parser for Vietnamese money, replacing five that disagreed.

Before this module, `"1.500 trieu"` was 1.5 triệu to the inventory tool and 1.5 tỷ to the
document conflict detector — a thousandfold gap in the two places most likely to quote a
customer a number. `"3 t"` meant 3 tỷ to one and 3 đồng to the other, `"3 million"` was
understood by one and ignored by the other, and the northern spelling `tỉ` was recognised by
exactly one regex out of five. See tests/test_utils/test_vnd_characterization.py for the
recorded evidence.

Two profiles, because the divergence was not purely accidental:

`CONVERSATIONAL` reads what a person types into a chat box. It accepts the bare `t`
abbreviation as tỷ ("căn 3t") and treats a dot as a decimal point, because someone writing
"2.5 tỷ" means two and a half billion.

`DOCUMENT` reads price tables lifted out of PDFs. It accepts English unit names and explicit
đồng units, and reads a dot as a thousands separator once the grouping is unambiguous for
that unit — "500.000 VND" is five hundred thousand đồng, "3.500 triệu" is 3500 triệu, but
"1.500 tỷ" is still 1,5 tỷ (see `_reads_dots_as_thousands`). It deliberately does *not*
accept a bare `t`, which in a spreadsheet cell is far more likely to be "tầng" or "tấn".

Both return whole đồng: there is no such thing as a fractional đồng in a price list, and an
`int` avoids the float-comparison surprises the old `float`-returning parser produced.
"""

import re
from enum import Enum

from backend.utils.text import strip_diacritics

_BILLION = 1_000_000_000
_MILLION = 1_000_000


class Profile(Enum):
    """Which unit vocabulary to read the input with."""

    CONVERSATIONAL = "conversational"
    DOCUMENT = "document"


# Diacritic stripping maps `tỷ` to `ty` and `tỉ` to `ti`, so both keys are required.
_CONVERSATIONAL_UNITS = {
    "ty": _BILLION,
    "ti": _BILLION,
    "t": _BILLION,
    "trieu": _MILLION,
    "tr": _MILLION,
}

_DOCUMENT_UNITS = {
    "ty": _BILLION,
    "ti": _BILLION,
    "billion": _BILLION,
    "trieu": _MILLION,
    "tr": _MILLION,
    "million": _MILLION,
    "vnd": 1,
    "dong": 1,
    "d": 1,
}

_UNITS: dict[Profile, dict[str, int]] = {
    Profile.CONVERSATIONAL: _CONVERSATIONAL_UNITS,
    Profile.DOCUMENT: _DOCUMENT_UNITS,
}


def _alternation(*spellings: str) -> str:
    """Longest spelling first, so `trieu` wins over `tr` and no match is truncated."""
    return "|".join(sorted(set(spellings), key=len, reverse=True))


# Exclude đồng and bare `t` to avoid matching fees or ordinary text as budgets.
BUDGET_UNIT_ALTERNATION = _alternation("tỷ", "tỉ", "ty", "ti", "triệu", "trieu", "tr")

# Bare `t` is only safe in tightly anchored price-range patterns.
BUDGET_UNIT_ALTERNATION_WITH_BARE_T = _alternation("tỷ", "tỉ", "ty", "ti", "triệu", "trieu", "tr", "t")

# Exclude bare `t` so floor and load values are not parsed as document prices.
DOCUMENT_UNIT_ALTERNATION = _alternation(
    "tỷ",
    "tỉ",
    "ty",
    "ti",
    "triệu",
    "trieu",
    "tr",
    "million",
    "billion",
    "vnd",
    "vnđ",
    "dong",
    "đồng",
    "đ",
)

# Broad vocabulary for callers that cannot use a narrower alternation.
UNIT_ALTERNATION = _alternation(
    "tỷ",
    "tỉ",
    "ty",
    "ti",
    "t",
    "triệu",
    "trieu",
    "tr",
    "million",
    "billion",
    "vnd",
    "vnđ",
    "dong",
    "đồng",
    "đ",
)

_GROUPED_THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3})+")
_MULTI_GROUP_THOUSANDS = re.compile(r"\d{1,3}(?:[.,]\d{3}){2,}")


def parse_vnd(number: str, unit: str | None, *, profile: Profile) -> int | None:
    """Convert a number and its unit to whole đồng, or None if the number is unreadable.

    Returns None rather than raising: every caller runs this inside a regex loop over
    free text, where one malformed match should skip that match rather than abort the
    scan. The old inventory parser raised ValueError on "1.500.000" and callers simply
    had no branch for it.
    """
    compact = (number or "").strip()
    if not compact:
        return None

    units = _UNITS[profile]
    key = strip_diacritics(unit or "").strip().lower()
    multiplier = units.get(key)

    if _reads_dots_as_thousands(compact, multiplier=multiplier, profile=profile):
        digits = re.sub(r"[.,]", "", compact)
        return int(digits) * (multiplier if multiplier is not None else 1)

    try:
        value = float(compact.replace(",", "."))
    except ValueError:
        return None

    return round(value * (multiplier if multiplier is not None else 1))


def _reads_dots_as_thousands(compact: str, *, multiplier: int | None, profile: Profile) -> bool:
    """Whether "3.500" means three thousand five hundred rather than three and a half.

    How many groups it takes to be sure depends on the unit, because the unit sets the scale
    at which a fraction stops being plausible:

    With đồng or triệu, one group is already unambiguous. "500.000 VND" is five hundred
    thousand đồng — nobody prints half a đồng — and "3.500 triệu" in a price table is 3500
    triệu, i.e. 3,5 tỷ. With tỷ it is not: "1.500 tỷ" is far more likely to be 1,5 tỷ than
    1500 tỷ, so billions need two groups ("1.500.000") before the grouping is beyond doubt.

    CONVERSATIONAL is stricter across the board. Someone typing into a chat box means a
    decimal point, so nothing short of two groups counts there whatever the unit.
    """
    if profile is not Profile.DOCUMENT or multiplier == _BILLION:
        return _MULTI_GROUP_THOUSANDS.fullmatch(compact) is not None
    return _GROUPED_THOUSANDS.fullmatch(compact) is not None
