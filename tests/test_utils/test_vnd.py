"""The unified VND parser: one answer per input, whichever code path asks."""

import pytest

from backend.utils.vnd import UNIT_ALTERNATION, Profile, parse_vnd

BILLION = 1_000_000_000
MILLION = 1_000_000


@pytest.mark.parametrize("unit", ["tỷ", "tỉ", "ty", "TỶ", " tỷ "])
def test_every_spelling_of_billion_is_accepted(unit):
    """`tỷ` and `tỉ` are the same word. Only one of the five original regexes knew that,
    so a northern-spelled budget silently parsed as a bare number three orders of
    magnitude too small."""
    assert parse_vnd("3", unit, profile=Profile.CONVERSATIONAL) == 3 * BILLION


@pytest.mark.parametrize("unit", ["triệu", "trieu", "tr", "TRIỆU"])
def test_every_spelling_of_million_is_accepted(unit):
    assert parse_vnd("800", unit, profile=Profile.CONVERSATIONAL) == 800 * MILLION


@pytest.mark.parametrize(("number", "expected"), [("2,5", 2.5), ("2.5", 2.5), ("3", 3.0)])
def test_both_decimal_separators_mean_the_same_thing(number, expected):
    """Vietnamese keyboards produce either; "2,5 tỷ" and "2.5 tỷ" are one price."""
    assert parse_vnd(number, "tỷ", profile=Profile.CONVERSATIONAL) == int(expected * BILLION)


def test_a_single_dot_group_stays_a_decimal():
    """ "1.500 tỷ" is one and a half billion, not fifteen hundred billion.

    Reading a lone three-digit group as a thousands separator is the failure mode this
    guards: it would inflate every conversational price by 1000x.
    """
    assert parse_vnd("1.500", "tỷ", profile=Profile.CONVERSATIONAL) == 1_500_000_000
    assert parse_vnd("1.500", "tỷ", profile=Profile.DOCUMENT) == 1_500_000_000


def test_document_profile_reads_grouped_thousands():
    """A price table prints "1.500.000 VND"; two or more groups cannot be a decimal."""
    assert parse_vnd("1.500.000", "VND", profile=Profile.DOCUMENT) == 1_500_000
    assert parse_vnd("2.500.000.000", "VND", profile=Profile.DOCUMENT) == 2_500_000_000


def test_bare_t_is_billions_only_in_conversation():
    """ "căn 3t" from a Sale means 3 tỷ. The same "3 t" in a spreadsheet cell is far more
    likely to be tầng or tấn, so the document profile refuses to guess."""
    assert parse_vnd("3", "t", profile=Profile.CONVERSATIONAL) == 3 * BILLION
    assert parse_vnd("3", "t", profile=Profile.DOCUMENT) == 3


def test_english_unit_names_are_document_only():
    assert parse_vnd("3", "million", profile=Profile.DOCUMENT) == 3 * MILLION
    assert parse_vnd("3", "billion", profile=Profile.DOCUMENT) == 3 * BILLION
    assert parse_vnd("3", "million", profile=Profile.CONVERSATIONAL) == 3


@pytest.mark.parametrize("unit", ["vnd", "dong", "đồng", "d"])
def test_explicit_dong_units_are_a_multiplier_of_one(unit):
    assert parse_vnd("250000", unit, profile=Profile.DOCUMENT) == 250_000


def test_an_absent_unit_means_plain_dong():
    assert parse_vnd("250000", None, profile=Profile.CONVERSATIONAL) == 250_000
    assert parse_vnd("250000", "", profile=Profile.DOCUMENT) == 250_000


@pytest.mark.parametrize("number", ["", "   ", "abc", "1.2.3", None])
def test_unreadable_input_returns_none_rather_than_raising(number):
    """Every caller runs this inside a regex loop over free text, where one malformed
    match must skip that match rather than abort the scan. The old inventory parser
    raised ValueError on "1.500.000" and no caller had a branch for it."""
    assert parse_vnd(number, "tỷ", profile=Profile.CONVERSATIONAL) is None


def test_the_result_is_always_whole_dong():
    """There is no fractional đồng in a price list, and an int avoids the float-comparison
    surprises the old float-returning parser produced."""
    result = parse_vnd("2,5", "tỷ", profile=Profile.CONVERSATIONAL)
    assert isinstance(result, int)
    assert result == 2_500_000_000


def test_unit_alternation_orders_longer_spellings_first():
    """Shared by the regexes that used to hand-list their own unit subset. `tr` before
    `trieu` in an alternation would truncate every "trieu" match to "tr"."""
    units = UNIT_ALTERNATION.split("|")
    assert units == sorted(units, key=len, reverse=True)
    assert {"tỷ", "tỉ", "trieu", "tr", "million", "billion"} <= set(units)


def test_both_profiles_agree_wherever_the_unit_is_unambiguous():
    """The whole point of the module: the same sentence cannot mean two different prices
    depending on which code path read it."""
    for number, unit in [("3", "tỷ"), ("3", "tỉ"), ("800", "tr"), ("2,5", "triệu"), ("1.500", "tỷ")]:
        conversational = parse_vnd(number, unit, profile=Profile.CONVERSATIONAL)
        document = parse_vnd(number, unit, profile=Profile.DOCUMENT)
        assert conversational == document, f"{number!r} {unit!r} still parses two ways"
