"""Proves the five VND parsers now agree, and pins the six inputs that used to split them.

This file started as a characterization of the disagreement: five call sites parsed
Vietnamese money and none of them matched. Every case below is annotated with what the old
implementations returned, so the regression these assertions guard is legible without
digging through git history.

The remaining asymmetries are deliberate and documented in backend/utils/vnd.py: the
CONVERSATIONAL profile accepts the bare `t` shorthand and reads a lone dot-group as a
decimal, while DOCUMENT accepts English unit names and reads printed thousands separators.
"""

import pytest

from backend.services import ingestion_service, inventory_service
from backend.utils.vnd import Profile, parse_vnd

BILLION = 1_000_000_000
MILLION = 1_000_000

# (number, unit, expected_dong, what the old parsers did)
FIXED = [
    ("3", "tỉ", 3 * BILLION, "was 3 đồng everywhere: only admin_observability's regex knew `tỉ`"),
    ("1.500", "trieu", 1_500 * MILLION, "inventory said 1,5 triệu and ingestion said 1,5 tỷ — 1000x apart"),
    ("1.500.000", "VND", 1_500_000, "inventory raised ValueError and no caller had a branch for it"),
    ("3", "million", 3 * MILLION, "inventory ignored the unit and returned 3 đồng"),
    ("3", "billion", 3 * BILLION, "inventory ignored the unit and returned 3 đồng"),
]


@pytest.mark.parametrize(("number", "unit", "expected", "history"), FIXED)
def test_previously_divergent_inputs_now_have_one_answer(number, unit, expected, history):
    assert parse_vnd(number, unit, profile=Profile.DOCUMENT) == expected, history


@pytest.mark.parametrize(
    ("number", "unit", "expected"),
    [
        ("3", "tỷ", 3 * BILLION),
        ("3", "ty", 3 * BILLION),
        ("3", "tỉ", 3 * BILLION),
        ("3", "triệu", 3 * MILLION),
        ("3", "trieu", 3 * MILLION),
        ("3", "tr", 3 * MILLION),
        ("2,5", "tỷ", 2_500_000_000),
        ("2.5", "tỷ", 2_500_000_000),
        ("1.500", "tỷ", 1_500_000_000),
    ],
)
def test_the_two_arithmetic_call_sites_agree(number, unit, expected):
    """`inventory_service` and `ingestion_service` both delegate to the shared parser now,
    so the same sentence cannot mean two different prices depending on which read it."""
    assert inventory_service._price_to_vnd(number, unit) == float(expected)
    assert ingestion_service._price_to_vnd(number, unit) == expected


def test_document_thousands_separators_survived_the_unification():
    """Printed price tables were the one place the old ingestion parser got right, and its
    rules are unit-dependent: a lone group is thousands for triệu/đồng but not for tỷ."""
    assert ingestion_service._price_to_vnd("500.000", "VND") == 500_000
    assert ingestion_service._price_to_vnd("3.500", "triệu") == 3_500 * MILLION
    assert ingestion_service._price_to_vnd("1.500", "tỷ") == 1_500 * MILLION


def test_unparseable_input_no_longer_raises():
    """The old inventory parser raised ValueError from inside a regex loop, which would
    abort a whole document scan over one malformed match."""
    assert inventory_service._price_to_vnd("abc", "tỷ") == 0.0
    assert ingestion_service._price_to_vnd("abc", "tỷ") == 0


def test_every_budget_regex_shares_one_unit_vocabulary():
    """`tỉ` was matched by one of the five patterns and `tr` was rejected by another, so a
    northern-spelled or abbreviated budget was silently dropped depending on the code path."""
    from backend.routers.admin_observability import _BUDGET_PATTERN
    from backend.services.memory_service import BUDGET_PATTERN
    from backend.services.search_criteria import _VAGUE_AROUND_PATTERN

    for pattern in (_BUDGET_PATTERN, BUDGET_PATTERN, _VAGUE_AROUND_PATTERN):
        assert pattern.search("tầm 3 tỉ") is not None, pattern.pattern
        assert pattern.search("tầm 800tr") is not None, pattern.pattern
        assert pattern.search("tầm 3 tỷ") is not None, pattern.pattern
