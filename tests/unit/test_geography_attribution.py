"""Geography attribution (BD-17; code review RV-002, RV-003, RV-084, RV-087, RV-089): a
figure counts as the researched city's only when its area name says so, never because the
name merely contains the city's. Fictional places only (Halden Bay, Norvania)."""

import pytest

from app.domain.geography import effective_level
from app.domain.models import CityIdentity, GeographyFit
from app.domain.place_names import place_key, place_keys
from app.domain.vocab import GeographyLevel, GeographyRelation, SlotStatus
from app.workflow.rules.gap_notes import gap_note
from app.workflow.rules.geography_fit import (
    PlaceCandidate,
    geography_fit,
    lookup_names,
    region_named,
)
from app.workflow.rules.other_places import place_matcher
from tests.unit.builders import claim

L = GeographyLevel
R = GeographyRelation
HALDEN = CityIdentity(
    city_id="city_hb", gazetteer_id="9000001", name="Halden Bay", ascii_name="Halden Bay",
    country_iso2="XN", country_iso3="XNV", country_name="Norvania", admin1_code="01",
    admin1_name="Coast", admin2_name=None, population=420000, lat=60.1, lon=5.2,
    languages=["nv", "en"],
)  # fmt: skip
SELF = PlaceCandidate("9000001", "Halden Bay", 60.1, 5.2, "01")
GREATER = PlaceCandidate("9000009", "Greater Halden Bay", 60.25, 5.45, "01")  # about 20 km
CITY_PLACE = PlaceCandidate("9000021", "Halden Bay City", 61.9, 5.2, "02")  # about 200 km
TWIN_ELSEWHERE = PlaceCandidate("9000030", "Halden Bay", 62.5, 8.0, "02")  # other region
TWIN_SAME_REGION = PlaceCandidate("9000031", "Halden Bay", 60.8, 6.2, "01")


def fit(
    level: GeographyLevel, name: str, *candidates: PlaceCandidate, region: bool = False
) -> GeographyFit:
    """As `match_quotes.fit_for`: only candidates sharing one of the lookup keys are passed."""
    keys = set(lookup_names(name))
    found = [c for c in candidates if c.keys & keys]
    return geography_fit(level, name, HALDEN, found, 75, region_in_source=region)


# --- one normal form for names --------------------------------------------------------


def test_place_keys_meet_whatever_the_punctuation_or_case() -> None:
    assert place_key("St. Ostra") == place_key("st ostra") == "st ostra"
    assert place_key("HALDEN BAY'S") == "halden bay"
    assert place_keys("Halden Bay", "Halden Bay", "HB", None) == ["halden bay", "hb"]


# --- rule 2: the full name before the name without area words ---------------------------


def test_a_distinct_place_named_greater_x_is_that_place_not_the_city() -> None:
    result = fit(L.CITY_WIDE, "Greater Halden Bay", SELF, GREATER)
    assert (result.relation, result.place_name) == (R.NEARBY, "Greater Halden Bay")


def test_a_distinct_place_named_x_city_is_that_place_not_the_city() -> None:
    assert fit(L.CITY_WIDE, "Halden Bay City", SELF, CITY_PLACE).relation is R.ELSEWHERE


# --- rule 4: the area words removed decide ------------------------------------------------


@pytest.mark.parametrize(
    ("level", "name", "relation"),
    [
        (L.CITY_WIDE, "Halden Bay", R.CITY),
        (L.CITY_WIDE, "City of Halden Bay", R.CITY),
        (L.CITY_WIDE, "Halden Bay Municipal Corporation", R.CITY),
        (L.CITY_WIDE, "Greater Halden Bay", R.CONTAINS_CITY),  # no such gazetteer place
        (L.METRO_REGION, "Halden Bay Metropolitan Region", R.CONTAINS_CITY),
        (L.DISTRICT, "Halden Bay district", R.CONTAINS_CITY),
        (L.CITY_WIDE, "Halden Bay Rural", R.UNRESOLVED),
        (L.CITY_WIDE, "Halden Bay urban wards", R.UNRESOLVED),
    ],
)
def test_area_words_around_the_city_name_decide_what_the_figure_covers(
    level: GeographyLevel, name: str, relation: R
) -> None:
    assert fit(level, name, SELF).relation is relation


# --- rule 5: a name merely containing the city's -----------------------------------------


@pytest.mark.parametrize(
    "name", ["North Halden Bay", "Halden Bay Cantonment", "Halden Bay and Kestrel Point"]
)
def test_a_name_that_only_contains_the_city_name_is_not_the_city(name: str) -> None:
    assert fit(L.CITY_WIDE, name, SELF).relation is R.UNRESOLVED


# --- rule 1: qualifiers ---------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["Halden Bay, Ostland", "Halden Bay (Ostland)", "Halden Bay, West Coast"]
)
def test_a_qualifier_naming_somewhere_else_makes_the_figure_not_the_citys(name: str) -> None:
    assert fit(L.CITY_WIDE, name, SELF).relation is R.UNRESOLVED


@pytest.mark.parametrize("name", ["Halden Bay, Coast", "Halden Bay (Norvania)"])
def test_the_citys_own_region_or_country_as_qualifier_is_fine(name: str) -> None:
    assert fit(L.CITY_WIDE, name, SELF).relation is R.CITY


# --- rule 3: places sharing the city's name (owner: drop unless settled) ---------------


def test_a_shared_name_with_nothing_to_settle_it_is_dropped() -> None:
    assert fit(L.CITY_WIDE, "Halden Bay", SELF, TWIN_ELSEWHERE).relation is R.UNRESOLVED


def test_a_shared_name_is_the_city_when_the_source_names_the_citys_region() -> None:
    result = fit(L.CITY_WIDE, "Halden Bay", SELF, TWIN_ELSEWHERE, region=True)
    assert result.relation is R.CITY


def test_a_shared_name_is_the_city_when_qualified_by_the_citys_region() -> None:
    assert fit(L.CITY_WIDE, "Halden Bay, Coast", SELF, TWIN_ELSEWHERE).relation is R.CITY


def test_a_namesake_in_the_citys_own_region_is_never_settled() -> None:
    result = fit(L.CITY_WIDE, "Halden Bay, Coast", SELF, TWIN_SAME_REGION, region=True)
    assert result.relation is R.UNRESOLVED


def test_the_region_check_reads_whole_words() -> None:
    assert region_named(HALDEN, "Health survey for the Coast region, 2024.")
    assert not region_named(HALDEN, "Results from the West Coastal belt.")


# --- national and state: exact names, never containment -------------------------------


@pytest.mark.parametrize(
    ("country", "label", "relation"),
    [
        ("Norvania", "Norvania", R.CONTAINS_CITY),
        ("Norvania", "all of Norvania", R.CONTAINS_CITY),
        ("Norvania", "South Norvania", R.ELSEWHERE),
        ("Norvania", "Norvania Minor", R.ELSEWHERE),
        ("Republic of Norvania", "Republic of Norvania", R.CONTAINS_CITY),
        ("Republic of Norvania", "Democratic Republic of Norvania", R.ELSEWHERE),
        ("Norvania", "nationwide", R.ELSEWHERE),  # which nation is not stated
    ],
)
def test_a_national_figure_must_name_the_citys_own_country(
    country: str, label: str, relation: R
) -> None:
    city = HALDEN.model_copy(update={"country_name": country})
    assert geography_fit(L.NATIONAL, label, city, [], 75).relation is relation


@pytest.mark.parametrize(
    ("label", "relation"),
    [("Coast", R.CONTAINS_CITY), ("Coast State", R.CONTAINS_CITY), ("West Coast", R.ELSEWHERE)],
)
def test_a_state_figure_must_name_the_citys_own_region(label: str, relation: R) -> None:
    assert geography_fit(L.STATE_PROVINCE, label, HALDEN, [], 75).relation is relation


# --- effective level and gap notes ------------------------------------------------------


def test_an_area_containing_the_city_never_counts_as_city_wide() -> None:
    containing = GeographyFit(relation=R.CONTAINS_CITY, place_name="Halden Bay", distance_km=0)
    c = claim(labels={"geography_name": "Greater Halden Bay"}, geography_fit=containing)
    assert effective_level(c) is L.METRO_REGION
    national = claim(labels={"geography_level": L.NATIONAL}, geography_fit=containing)
    assert effective_level(national) is L.NATIONAL


def test_a_nearby_figure_is_never_called_city_wide_in_the_gap_note() -> None:
    near = GeographyFit(relation=R.NEARBY, place_name="Kestrel Point", distance_km=28)
    best = claim(labels={"geography_name": "Kestrel Point"}, geography_fit=near)
    note = gap_note(SlotStatus.ANSWERED_WIDER_GEO, best=best)
    assert note is not None
    assert "a nearby place (Kestrel Point" in note
    assert "city-wide" not in note


# --- other-place rule: the city's own names in any case (RV-084) ------------------------


def test_an_upper_case_title_naming_the_city_is_not_ranked_later() -> None:
    rows = [
        {"gazetteer_id": "9000001", "name": "Halden Bay", "ascii_name": "Halden Bay",
         "alternate_names": []},
        {"gazetteer_id": "9000002", "name": "Port Ostra", "ascii_name": "Port Ostra",
         "alternate_names": []},
    ]  # fmt: skip
    matcher = place_matcher(HALDEN, rows)
    assert not matcher.names_other_place("HALDEN BAY AND PORT OSTRA HEALTH", "", "https://a.test/")
