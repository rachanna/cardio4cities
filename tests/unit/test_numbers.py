"""Number parsing (LLD-2 §4.2): every row of the table, plus negative cases."""

from decimal import Decimal

import pytest

from app.workflow.rules.numbers import COUNT, PER_100K, PERCENT, UNPARSED, ParsedValue, parse_value

D = Decimal


@pytest.mark.parametrize(
    ("written", "expected"),
    [
        ("21.7%", ParsedValue(D("21.7"), PERCENT)),
        ("21.7 %", ParsedValue(D("21.7"), PERCENT)),
        ("21.7 per cent", ParsedValue(D("21.7"), PERCENT)),
        ("21.7 percent", ParsedValue(D("21.7"), PERCENT)),
        ("21,7%", ParsedValue(D("21.7"), PERCENT)),
        ("9,5 %", ParsedValue(D("9.5"), PERCENT)),
        ("1,234,567", ParsedValue(D("1234567"), COUNT)),
        ("1.234.567", ParsedValue(D("1234567"), COUNT)),
        ("1 234 567", ParsedValue(D("1234567"), COUNT)),
        ("45 per 100,000", ParsedValue(D("45"), PER_100K)),
        ("45 per 100 000", ParsedValue(D("45"), PER_100K)),
        ("20–25%", ParsedValue(None, PERCENT, D("20"), D("25"))),
        ("20-25 %", ParsedValue(None, PERCENT, D("20"), D("25"))),
        ("20 to 25 %", ParsedValue(None, PERCENT, D("20"), D("25"))),
        ("21.7% (95% CI 19.8–23.6)", ParsedValue(D("21.7"), PERCENT, D("19.8"), D("23.6"))),
        ("21.7% (95% CI: 19.8 to 23.6)", ParsedValue(D("21.7"), PERCENT, D("19.8"), D("23.6"))),
    ],
)
def test_table_rows(written: str, expected: ParsedValue) -> None:
    assert parse_value(written) == expected


def test_range_is_never_collapsed_to_a_midpoint() -> None:
    """WD-04: a computed number would not appear in any source."""
    result = parse_value("20-25%")

    assert result.value_num is None
    assert (result.lower, result.upper) == (D("20"), D("25"))


@pytest.mark.parametrize(
    "written", ["1 in 3", "one third", "about a fifth", "up to 30%", "n/a", ""]
)
def test_words_and_approximations_are_unparsed(written: str) -> None:
    assert parse_value(written) == UNPARSED


def test_a_year_alone_is_not_a_value() -> None:
    assert parse_value("2019") == UNPARSED


def test_ambiguous_separator_is_thousands_when_three_digits_follow() -> None:
    assert parse_value("1,234") == ParsedValue(D("1234"), COUNT)
    assert parse_value("1.234") == ParsedValue(D("1234"), COUNT)


def test_ambiguous_separator_otherwise_unparsed() -> None:
    assert parse_value("1,2345") == UNPARSED
    assert parse_value("12,34,567") == UNPARSED
