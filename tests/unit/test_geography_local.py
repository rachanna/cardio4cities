"""Local evidence kept (BD-51): a group or area named "in" or "of" the city counts as part
of it, never the whole city; the city's real alternate names count in the evidence while
codes do not; and one domain cannot take all of a question's pages in a round. Fictional
Halden Bay, Norvania."""

from app.domain.geography import effective_level
from app.domain.models import GeographyFit
from app.domain.place_names import real_alternate_names
from app.domain.vocab import GeographyLevel, GeographyRelation, PublisherClass
from app.workflow.rules.geography_fit import area_named, city_named, geography_fit
from app.workflow.rules.selection import Candidate, spread_domains
from tests.unit.builders import claim
from tests.unit.test_geography_attribution import HALDEN

L = GeographyLevel
R = GeographyRelation
OLD_NAME = HALDEN.model_copy(update={"alternate_names": ["Haldenvik"]})


def fit(name: str, evidence: bool = True, level: GeographyLevel = L.CITY_WIDE) -> GeographyFit:
    return geography_fit(level, name, OLD_NAME, [], 75, city_named_in_evidence=evidence)


def test_a_group_in_the_city_is_kept_as_a_group_never_the_whole_city() -> None:
    for label in (
        "underprivileged urban community in Halden Bay",
        "urban slums of Halden Bay city",
        "fishing households within the Halden Bay",
        "low-income wards across Halden Bay",
    ):
        got = fit(label)
        assert (got.relation, got.level) == (R.CITY, L.SUB_CITY_POPULATION), label


def test_the_group_rule_needs_the_city_named_in_the_evidence_and_the_city_last() -> None:
    assert (
        fit("underprivileged urban community in Halden Bay", evidence=False).relation
        is R.UNRESOLVED
    )
    assert fit("Halden Bay community clinics").relation is R.UNRESOLVED  # no "in ... city"
    assert fit("rural Halden Bay").relation is R.UNRESOLVED  # rural: not the city (rule 4)
    assert fit("Halden Bay city").relation is R.CITY  # the city itself, as before
    assert fit("Halden Bay city").level is None


def test_a_group_counts_at_its_own_level_and_keeps_its_label() -> None:
    group = claim(
        labels={"geography_level": "city_wide", "geography_name": "community in Halden Bay"},
        geography_fit=fit("underprivileged urban community in Halden Bay"),
    )
    assert effective_level(group) is L.SUB_CITY_POPULATION
    assert group.labels.geography_level is L.CITY_WIDE


def test_real_alternate_names_count_in_the_evidence_and_codes_do_not() -> None:
    kept = real_alternate_names(
        ["HBY", "Haldenvik", "haldenvik", "Halden-Vik", "HB", "halden bay", "Hal", "Hłd 7"],
        "Halden Bay",
        "Halden Bay",
    )
    assert kept == ["Haldenvik", "Halden-Vik"]
    assert city_named(OLD_NAME, ["The Haldenvik clinic opened in 1990."])
    assert not city_named(HALDEN, ["The Haldenvik clinic opened in 1990."])  # no alternates
    assert area_named("Halden Bay", OLD_NAME, ["Haldenvik Medical College treats adults."])


def _c(url: str, domain: str) -> Candidate:
    return Candidate(url, domain, PublisherClass.GOVERNMENT, 1)


def test_one_domain_cannot_take_all_of_a_questions_pages() -> None:
    ranked = [
        _c("https://city.gov.xn/a", "city.gov.xn"),
        _c("https://city.gov.xn/b", "city.gov.xn"),
        _c("https://city.gov.xn/c", "city.gov.xn"),
        _c("https://encyclopedia.xn/halden-bay", "encyclopedia.xn"),
    ]
    assert [c.url for c in spread_domains(ranked, 3, 2)] == [
        "https://city.gov.xn/a",
        "https://city.gov.xn/b",
        "https://encyclopedia.xn/halden-bay",
    ]
    only_one_site = ranked[:3]
    assert len(spread_domains(only_one_site, 3, 2)) == 3  # places left are still filled
