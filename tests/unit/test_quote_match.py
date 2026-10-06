"""Quote normalisation and matching (LLD-2 §4.1, AT-09)."""

import pytest

from app.workflow.rules.quotes import QuoteDrop, QuoteMatch, match_quote, normalise_text
from tests.unit.builders import quote_params

SOURCE = (
    "Annual report of the Norvania Health Directorate.\n"
    "In Halden Bay, 31.2% of adults aged 30–79 had raised blood pressure in 2024,\n"
    "according to the city’s “heart health” survey of 2,400 residents."
)


def _match(quote: str, source: str = SOURCE, value: str | None = None) -> QuoteMatch | QuoteDrop:
    return match_quote(quote, source, quote_params(), value)


def test_exact_quote_maps_back_to_original_offsets() -> None:
    quote = "In Halden Bay, 31.2% of adults aged 30–79 had raised blood pressure in 2024"

    result = _match(quote)

    assert isinstance(result, QuoteMatch)
    assert SOURCE[result.span_start : result.span_end] == quote


def test_curly_quotes_match_straight_quotes() -> None:
    result = _match('according to the city\'s "heart health" survey of 2,400 residents')

    assert isinstance(result, QuoteMatch)
    assert SOURCE[result.span_start : result.span_end].startswith("according to the city’s")


def test_pdf_hyphenation_across_lines_is_joined() -> None:
    source = "The screening pro-\n  gramme reached most clinics in Halden Bay during 2024."

    result = _match("The screening programme reached most clinics in Halden Bay", source)

    assert isinstance(result, QuoteMatch)
    assert source[result.span_start : result.span_end].startswith("The screening pro-\n")


def test_double_spaces_and_line_breaks_collapse() -> None:
    source = "Coverage  of the   programme\nwas  limited in the  western districts of Halden Bay."

    assert isinstance(
        _match("Coverage of the programme was limited in the western", source), QuoteMatch
    )


def test_one_changed_word_drops_the_claim() -> None:
    """AT-09: a quote that does not occur verbatim in the source is dropped."""
    result = _match("In Halden Bay, 31.2% of adults aged 30-79 had high blood pressure in 2024")

    assert result == QuoteDrop("quote_not_found")


def test_case_differs_drops_the_claim() -> None:
    """AT-09: matching is case-sensitive; no fuzzy matching."""
    result = _match("in halden bay, 31.2% of adults aged 30-79 had raised blood pressure")

    assert result == QuoteDrop("quote_not_found")


def test_value_in_source_but_not_in_quote_drops_the_claim() -> None:
    result = _match("of adults aged 30-79 had raised blood pressure in 2024", value="31.2%")

    assert result == QuoteDrop("value_not_in_quote")


def test_value_inside_quote_is_kept() -> None:
    result = _match("31.2% of adults aged 30-79 had raised blood pressure", value="31.2%")

    assert isinstance(result, QuoteMatch)


def test_non_english_quote_matched_in_original_language() -> None:
    source = "En Halden Bay, el 31,2 % de los adultos de 30 a 79 años tenía hipertensión."

    result = _match("el 31,2 % de los adultos de 30 a 79 años tenía hipertensión", source, "31,2 %")

    assert isinstance(result, QuoteMatch)


def test_decomposed_accents_match_composed() -> None:
    source = "Los adultos de Halden Bay tenian una tasa de hipertensión elevada en 2024."

    assert isinstance(_match("una tasa de hipertensión elevada en 2024", source), QuoteMatch)


@pytest.mark.parametrize("quote", ["Too short", " ".join(["word"] * 61)])
def test_quote_length_outside_bounds_is_dropped(quote: str) -> None:
    assert _match(quote) == QuoteDrop("quote_length")


def test_soft_hyphen_and_zero_width_characters_are_removed() -> None:
    assert normalise_text("hyper­tension​ rates") == "hypertension rates"


TABLE_SOURCE = (
    "[page 4]\nIndicator Women Men\n"
    "Raised blood pressure 29.0% 33.5%\n"
    "Controlled hypertension 21.1% 15.9%\n"
    "Total 25.2% 25.2%\n"
    "[page 5]\nAnnex table repeated\n"
    "Total 25.2% 25.2%\n"
)


def test_short_quote_unique_in_source_is_matched() -> None:
    """BD-08: a table row under six words is accepted when it occurs exactly once."""
    quote = "Controlled hypertension 21.1% 15.9%"

    result = _match(quote, TABLE_SOURCE, "21.1%")

    assert isinstance(result, QuoteMatch)
    assert TABLE_SOURCE[result.span_start : result.span_end] == quote


def test_short_quote_occurring_twice_is_dropped() -> None:
    """BD-08: a repeated short quote could anchor the value to the wrong row."""
    assert _match("Total 25.2% 25.2%", TABLE_SOURCE, "25.2%") == QuoteDrop("quote_not_unique")


def test_short_quote_still_needs_its_value_and_exact_text() -> None:
    assert _match("Controlled hypertension 21.1% 15.9%", TABLE_SOURCE, "33.5%") == QuoteDrop(
        "value_not_in_quote"
    )
    assert _match("Controlled hypertension 21.1% 16.9%", TABLE_SOURCE) == QuoteDrop(
        "quote_not_found"
    )


def test_two_word_quote_is_too_short_even_if_unique() -> None:
    assert _match("Indicator Women", TABLE_SOURCE) == QuoteDrop("quote_length")


def test_long_quote_keeps_first_occurrence_rule() -> None:
    """Quotes of six words or more are unchanged: first occurrence, no uniqueness check."""
    source = "The survey covered adults in Halden Bay. " * 2

    result = _match("The survey covered adults in Halden Bay.", source)

    assert isinstance(result, QuoteMatch)
    assert result.span_start == 0


# --- layout read as space, and a quote that starts mid-sentence (BD-47) -------------------


def test_list_markers_and_bullets_between_a_lead_in_and_its_item_are_spaces() -> None:
    """A live run lost quotes running from a lead-in into its first list item, and every
    row of a two-column list whose PDF bullet glyph sat between name and action."""
    listed = (
        "The aims for Halden Bay are that by 2029:\n"
        "- 80% of adults with hypertension are diagnosed."
    )
    glyph = "Coast Heart Trust \uf0b7 develop resources on salt for every clinic in Halden Bay"
    bullet = "Coast Heart Trust \u2022 develop resources on salt for every clinic in Halden Bay"

    lead_in = (
        "The aims for Halden Bay are that by 2029: 80% of adults with hypertension are diagnosed."
    )
    action = "Coast Heart Trust develop resources on salt for every clinic in Halden Bay"
    assert isinstance(_match(lead_in, listed), QuoteMatch)
    assert isinstance(_match(action, glyph), QuoteMatch)
    assert isinstance(_match(action, bullet), QuoteMatch)


def test_a_minus_sign_a_hyphen_and_the_middle_dot_stay_text() -> None:
    """Only a line-start '-' or '*' followed by a space is a list marker; some journals
    print the middle dot as the decimal point."""
    assert normalise_text("change:\n-8% in Halden Bay") == "change: -8% in Halden Bay"
    assert normalise_text("well-known") == "well-known"
    assert normalise_text("31\u00b75%") == "31\u00b75%"


def test_a_quote_may_differ_from_the_source_only_in_its_first_letter_s_case() -> None:
    source = "Since then in 2022-24 this had reduced to 73.6 per 100,000 in Halden Bay overall."

    starts_mid_sentence = _match(
        "In 2022-24 this had reduced to 73.6 per 100,000 in Halden Bay", source
    )
    assert isinstance(starts_mid_sentence, QuoteMatch)
    assert source[starts_mid_sentence.span_start : starts_mid_sentence.span_end].startswith(
        "in 2022"
    )
    other_letter = _match("in 2022-24 This had reduced to 73.6 per 100,000 in Halden Bay", source)
    assert other_letter == QuoteDrop("quote_not_found")
