"""Label evidence and geography fit (BD-10): pure rules, fictional places only."""

from datetime import date

import pytest
import yaml

from app.domain.badges import badges
from app.domain.geography import effective_level
from app.domain.models import CityIdentity, GeographyFit
from app.domain.vocab import (
    Badge,
    GeographyLevel,
    GeographyRelation,
    PeriodType,
    Sex,
    SlotStatus,
)
from app.prompts.checker.context import ages, build_user_message, population
from app.workflow.rules.geography_fit import (
    PlaceCandidate,
    distance_km,
    geography_fit,
    lookup_names,
)
from app.workflow.rules.label_evidence import clear_labels, locate_label_quotes
from app.workflow.rules.slot_status import slot_status
from app.workflow.rules.thresholds import threshold_code, threshold_table
from tests.unit.builders import CITY_SLOT, badge_params, claim, labels, quote_params, slot
from tests.unit.test_comparability import THRESHOLDS

WINDOW = (
    "Results. 31.5% of adults with hypertension had their blood pressure under control. "
    "Methods. The survey interviewed adults aged 18 and over in their homes between March "
    "and October 2024 across the whole of Halden Bay."
)
PERIOD = "interviewed adults aged 18 and over in their homes between March and October 2024"


# --- label evidence ----------------------------------------------------------------


def test_a_located_period_quote_keeps_the_period_and_records_document_offsets() -> None:
    ev = locate_label_quotes({"period": PERIOD}, WINDOW, 1000, labels(), quote_params())
    start, end = ev.spans["period"]
    assert WINDOW[start - 1000 : end - 1000] == PERIOD
    assert ev.cleared == frozenset()


def test_a_period_quote_without_the_labelled_year_clears_the_period() -> None:
    wrong = labels(reference_start=date(2023, 1, 1), reference_end=date(2023, 12, 31))
    ev = locate_label_quotes({"period": PERIOD}, WINDOW, 0, wrong, quote_params())
    assert ev.spans == {}
    assert ev.cleared == {"period"}
    cleared = clear_labels(wrong, ev.cleared)
    assert (cleared.reference_start, cleared.reference_end) == (None, None)
    assert cleared.period_type is PeriodType.PUBLICATION_DATE_PROXY


def test_unlocated_population_is_cleared_but_geography_never_is() -> None:
    quotes = {
        "population": "adults aged 40 to 69 in rural homes",
        "geography": "the whole of Norvania",
    }
    ev = locate_label_quotes(quotes, WINDOW, 0, labels(), quote_params())  # type: ignore[arg-type]
    assert ev.cleared == {"population"}
    cleared = clear_labels(labels(), ev.cleared)
    assert (cleared.population_age_min, cleared.population_age_max) == (None, None)
    assert cleared.population_sex is Sex.NOT_STATED
    assert cleared.geography_name == "Halden Bay"


def test_empty_label_quotes_change_nothing() -> None:
    ev = locate_label_quotes(
        {"period": None, "population": " "}, WINDOW, 0, labels(), quote_params()
    )
    assert (ev.spans, ev.cleared) == ({}, frozenset())


# --- geography fit -------------------------------------------------------------------

HALDEN = CityIdentity(
    city_id="city_x", gazetteer_id="9000001", name="Halden Bay", ascii_name="Halden Bay",
    country_iso2="XN", country_iso3="XNV", country_name="Norvania", admin1_code="01",
    admin1_name="West Coast", admin2_name=None, population=420000, lat=60.1, lon=5.2,
    languages=["nv", "en"],
)  # fmt: skip
SELF = PlaceCandidate("9000001", "Halden Bay", 60.1, 5.2)
KESTREL = PlaceCandidate("9000005", "Kestrel Point", 60.3, 5.5)  # about 28 km
OSTRA = PlaceCandidate("9000002", "Port Ostra", 61.0, 6.0)  # about 109 km
SATELLITE = PlaceCandidate("9000009", "New Halden Bay", 60.15, 5.25)
L = GeographyLevel
R = GeographyRelation


def fit(level: GeographyLevel, name: str, *candidates: PlaceCandidate) -> GeographyFit:
    return geography_fit(level, name, HALDEN, candidates, nearby_km=75)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Port Ostra district", ["port ostra"]),
        ("Kestrel Point - West Coast", ["kestrel point", "kestrel point west coast"]),
        ("Greater Halden Bay Municipal Corporation", ["halden bay"]),
        ("Halden Bay's urban wards", ["halden bay"]),
        (
            "nine districts (Port Ostra and Kestrel Point)",
            ["nine", "nine port ostra and kestrel point"],
        ),
    ],
)
def test_lookup_names_strip_area_words_and_take_the_leading_segment(
    name: str, expected: list[str]
) -> None:
    assert lookup_names(name) == expected


def test_distance_is_great_circle_kilometres() -> None:
    assert round(distance_km(60.1, 5.2, 60.3, 5.5)) == 28


@pytest.mark.parametrize(
    ("level", "name", "candidates", "relation"),
    [
        (L.CITY_WIDE, "Halden Bay", (SELF,), R.CITY),
        (L.SUB_CITY_AREA, "Halden Bay's harbour wards", (), R.CITY),
        (L.METRO_REGION, "Halden Bay Metropolitan Region", (SELF,), R.CONTAINS_CITY),
        (L.DISTRICT, "Halden Bay district", (SELF,), R.CONTAINS_CITY),
        (L.STATE_PROVINCE, "West Coast", (), R.CONTAINS_CITY),
        (L.STATE_PROVINCE, "Inland", (), R.ELSEWHERE),
        (L.NATIONAL, "Norvania", (), R.CONTAINS_CITY),
        (L.NATIONAL, "Ostrovia", (), R.ELSEWHERE),
        (L.GLOBAL, "world", (), R.CONTAINS_CITY),
        (L.CITY_WIDE, "Kestrel Point", (KESTREL,), R.NEARBY),
        (L.DISTRICT, "Port Ostra district", (OSTRA,), R.ELSEWHERE),
        (L.SUB_CITY_AREA, "Kestrel Point", (KESTREL,), R.NEARBY),  # never the city itself
        (L.CITY_WIDE, "New Halden Bay", (SATELLITE,), R.NEARBY),  # a satellite town
        (L.DISTRICT, "nine districts (Port Ostra and Kestrel Point)", (), R.UNRESOLVED),
    ],
)
def test_geography_fit(
    level: GeographyLevel, name: str, candidates: tuple[PlaceCandidate, ...], relation: R
) -> None:
    assert fit(level, name, *candidates).relation is relation


def test_nearest_candidate_decides_and_its_distance_is_recorded() -> None:
    result = fit(L.CITY_WIDE, "Port Ostra", OSTRA, KESTREL)
    assert (result.relation, result.place_name, result.distance_km) == (
        R.NEARBY,
        "Kestrel Point",
        28,
    )


# --- effective level: a nearby figure is never city-level --------------------------


def nearby(level: GeographyLevel = L.CITY_WIDE) -> GeographyFit:
    return GeographyFit(relation=R.NEARBY, place_name="Kestrel Point", distance_km=28)


def test_a_nearby_towns_city_wide_figure_counts_as_district_wide() -> None:
    c = claim(labels={"geography_name": "Kestrel Point"}, geography_fit=nearby())
    assert effective_level(c) is L.DISTRICT
    national = claim(labels={"geography_level": L.NATIONAL}, geography_fit=nearby())
    assert effective_level(national) is L.NATIONAL
    assert effective_level(claim()) is L.CITY_WIDE


def test_a_nearby_figure_carries_not_city_level_and_answers_only_as_wider_area() -> None:
    c = claim(labels={"geography_name": "Kestrel Point"}, geography_fit=nearby())
    assert badges(c, CITY_SLOT, date(2026, 10, 3), badge_params()).main is Badge.NOT_CITY_LEVEL
    s = slot("S04", accepted_levels=[L.CITY_WIDE])
    assert slot_status(s, [c], 1, []) is SlotStatus.ANSWERED_WIDER_GEO
    assert slot_status(s, [claim()], 1, []) is SlotStatus.ANSWERED


# --- checker input: unstated labels assert nothing ----------------------------------


@pytest.mark.parametrize(
    ("low", "high", "text"),
    [(18, None, "aged 18 and over"), (None, 69, "aged up to 69"), (18, 69, "aged 18-69"),
     (None, None, "age not stated")],
)  # fmt: skip
def test_open_age_ranges_read_naturally(low: int | None, high: int | None, text: str) -> None:
    assert ages(low, high) == text


def test_unstated_population_reads_not_stated_never_general() -> None:
    text = population(labels(population_group=None, setting=None, population_sex=Sex.NOT_STATED))
    assert "general" not in text
    assert text.count("not stated") == 3


def test_label_passages_follow_the_quote_passage_each_in_its_own_source_block() -> None:
    message = build_user_message(
        "Claim.", "31.5%", labels(), "src_1", "government", None, "QUOTE PASSAGE",
        [("period", "PERIOD PASSAGE")],
    )  # fmt: skip
    assert message.index("passage around the quote:") < message.index("QUOTE PASSAGE")
    assert message.index("QUOTE PASSAGE") < message.index("passage stating the period:")
    assert message.count('<source id="src_1">') == 2


# --- thresholds ----------------------------------------------------------------------


def test_control_defined_as_below_140_and_90_is_the_140_90_threshold() -> None:
    table = threshold_table(yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8")))
    assert threshold_code("SBP < 140 and DBP < 90 mmHg", table) == "bp_140_90"
    assert threshold_code("systolic <130 and diastolic <80", table) == "bp_130_80"


@pytest.mark.parametrize(
    ("start", "end", "precision", "text"),
    [
        (date(2024, 1, 1), date(2024, 12, 31), "year", "2024"),
        (date(2018, 1, 1), date(2019, 12, 31), "year", "2018 to 2019"),
        (date(2023, 3, 1), date(2023, 10, 31), "month", "2023-03 to 2023-10"),
        (date(2024, 5, 2), date(2024, 5, 2), "day", "2024-05-02"),
        (None, None, None, "not stated"),
    ],
)
def test_checker_sees_the_period_at_the_precision_the_source_stated(
    start: date | None, end: date | None, precision: str | None, text: str
) -> None:
    """Golden set: "2024-01-01 to 2024-12-31" made the checker report a period mismatch."""
    from app.prompts.checker.context import _period

    period_type = PeriodType.PERIOD if start else PeriodType.PUBLICATION_DATE_PROXY
    stated = labels(reference_start=start, reference_end=end, reference_precision=precision,
                    period_type=period_type)  # fmt: skip
    assert _period(stated) == text
