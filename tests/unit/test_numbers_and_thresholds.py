"""Numbers, quotes and thresholds (BD-33; code review RV-021, RV-022, RV-085, RV-086).
Fictional text only."""

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from app.domain.params import QuoteParams
from app.workflow.rules.comparability import slug
from app.workflow.rules.numbers import PERCENT, parse_number, parse_value
from app.workflow.rules.quotes import QuoteDrop, match_quote
from app.workflow.rules.thresholds import threshold_code, threshold_table

PARAMS = QuoteParams(min_words=6, max_words=60, min_words_unique=3)
TABLE = threshold_table(
    yaml.safe_load((Path(__file__).resolve().parents[2] / "reference" / "thresholds.yaml")
                   .read_text(encoding="utf-8"))
)  # fmt: skip


# --- RV-021: the value stands as a whole number in the quote -------------------------------


@pytest.mark.parametrize(
    ("value", "found"),
    [("7%", False), ("17%", True), ("7.5%", False), ("27.5%", True), ("31,5 %", True)],
)
def test_the_value_must_stand_whole_in_the_quote(value: str, found: bool) -> None:
    text = "In Halden Bay, 17% of adults and 27.5% of older adults had 31,5 % coverage."
    quote = "17% of adults and 27.5% of older adults had 31,5 % coverage"
    result = match_quote(quote, text, PARAMS, value)
    assert (not isinstance(result, QuoteDrop)) is found


# --- RV-022: grouped numbers ------------------------------------------------------------------


def test_a_leading_zero_is_never_a_thousands_group() -> None:
    assert parse_number("0.125") == Decimal("0.125")
    assert parse_number("1.204") == Decimal("1204")
    assert parse_number("012,345") is None


@pytest.mark.parametrize("written", ["1.000%", "1,000 %", "2.500 to 3.000%"])
def test_a_percentage_with_one_three_digit_group_is_never_guessed(written: str) -> None:
    assert parse_value(written).unparsed


def test_ordinary_percentages_still_parse() -> None:
    parsed = parse_value("0.125%")
    assert (parsed.value_num, parsed.unit) == (Decimal("0.125"), PERCENT)
    assert parse_value("31,5 %").value_num == Decimal("31.5")
    assert parse_value("0,125%").value_num == Decimal("0.125")  # a leading zero: a decimal


# --- RV-086: thresholds -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("definition", "code"),
    [
        ("systolic ≥140mmHg or diastolic ≥90mmHg", "bp_140_90"),
        ("BP ⩾140/90 mmHg", "bp_140_90"),
        ("blood pressure below 140/90", "bp_140_90"),
        ("SBP>=130 or DBP>=80", "bp_130_80"),
        ("2-h plasma glucose ≥140 mg/dL", None),  # a glucose test, not a blood pressure
        ("fasting plasma glucose ≥ 7.0 mmol/L", "fpg_7_0"),
        ("systolic 1400 mmHg", None),
    ],
)
def test_thresholds_are_coded_from_the_case_definition(definition: str, code: str | None) -> None:
    assert threshold_code(definition, TABLE) == code


# --- RV-085: slugs in every script ---------------------------------------------------------


def test_slugs_keep_letters_of_every_script() -> None:
    assert slug("  Halden-Báy (city) ") == "halden-bay-city"
    first, second = slug("港南区"), slug("港北区")
    assert first
    assert second
    assert first != second
