"""Label integrity (BD-22; code review RV-006, RV-007, RV-017, RV-028, RV-099): labels hold
only what the located evidence states, publication dates come from metadata, and the
Not city-level badge follows a subgroup or a narrow setting, not free-text wording.
Fictional Halden Bay only."""

from datetime import date

import pytest

from app.adapters.parse.documents import DocumentParser
from app.domain.badges import badges
from app.domain.confidence import REPRESENTATIVENESS_POINTS
from app.domain.models import CityIdentity
from app.domain.ranking import REPRESENTATIVENESS_RANK
from app.domain.vocab import (
    Badge,
    ClaimFlag,
    DatePrecision,
    GeographyLevel,
    PeriodType,
    Representativeness,
    Setting,
)
from app.workflow.rules.geography_fit import area_named
from app.workflow.rules.label_evidence import keep_located
from app.workflow.rules.numbers import read_sample_size
from tests.unit.builders import badge_params, claim, labels

R = Representativeness
HALDEN = CityIdentity(
    city_id="city_hb", gazetteer_id="9000001", name="Halden Bay", ascii_name="Halden Bay",
    country_iso2="XN", country_iso3="XNV", country_name="Norvania", admin1_code="01",
    admin1_name="Coast", admin2_name=None, population=420000, lat=60.1, lon=5.2,
    languages=["nv", "en"],
)  # fmt: skip
QUOTE = (
    "Among 2,400 adults aged 30-79 in Halden Bay, 31.2% had hypertension (SBP>=140 and/or "
    "DBP>=90, or on medication) in the 2024 household survey"
)


# --- RV-006: numbers the evidence does not state are cleared ------------------------------


def test_labels_whose_numbers_are_located_are_kept() -> None:
    kept = keep_located(labels(), [QUOTE])
    assert kept.cleared == ()
    assert kept.labels == labels()


def test_an_age_band_the_evidence_does_not_state_is_cleared() -> None:
    kept = keep_located(labels(population_age_min=18, population_age_max=69), [QUOTE])
    assert kept.cleared == ("age_band",)
    assert (kept.labels.population_age_min, kept.labels.population_age_max) == (None, None)


def test_a_sample_size_the_evidence_does_not_state_is_cleared() -> None:
    kept = keep_located(labels(sample_size=1204), [QUOTE])
    assert kept.cleared == ("sample_size",)
    assert kept.labels.sample_size is None


def test_a_case_definition_with_other_numbers_is_cleared_with_its_threshold() -> None:
    """A threshold the source never states would make false agreement or disagreement."""
    kept = keep_located(labels(case_definition="below 130/80 mmHg", threshold_code="bp_130_80"),
                        [QUOTE])  # fmt: skip
    assert kept.cleared == ("case_definition",)
    assert (kept.labels.case_definition, kept.labels.threshold_code) == (None, None)


def test_a_case_definition_without_numbers_is_left_to_the_checker() -> None:
    kept = keep_located(labels(case_definition="doctor-diagnosed", threshold_code=None), [QUOTE])
    assert kept.labels.case_definition == "doctor-diagnosed"


def test_a_period_whose_years_the_evidence_does_not_state_becomes_a_proxy() -> None:
    """An empty label quote used to be trusted as "stated in the quote" unchecked."""
    stated = labels(reference_start=date(2022, 1, 1), reference_end=date(2022, 12, 31))
    kept = keep_located(stated, [QUOTE])
    assert kept.cleared == ("period",)
    assert kept.labels.period_type is PeriodType.PUBLICATION_DATE_PROXY
    assert kept.labels.reference_end is None


def test_a_period_span_written_short_still_states_its_end_year() -> None:
    span = labels(reference_start=date(2023, 1, 1), reference_end=date(2024, 12, 31))
    assert keep_located(span, [QUOTE.replace("2024 household", "2023-24 household")]).cleared == ()


def test_a_number_inside_another_is_not_stated() -> None:
    """ "30" is not in "130", and "7" is not in "7.5"."""
    one_age = labels(population_age_min=30, population_age_max=None)
    assert "age_band" in keep_located(one_age, ["systolic 130 mmHg"]).cleared
    assert "sample_size" in keep_located(labels(sample_size=7), ["7.5% of adults"]).cleared


def test_located_text_from_label_passages_counts() -> None:
    methods = "The survey interviewed 2,400 adults aged 30-79 between March and October 2024."
    short_quote = "31.2% had hypertension (SBP>=140 and/or DBP>=90, or on medication)"
    assert keep_located(labels(), [short_quote, methods]).cleared == ()


@pytest.mark.parametrize(
    ("written", "count"),
    [("n = 1,204", 1204), ("1 204 adults", 1204), ("300", 300), ("N=2.410", 2410),
     ("12.5", None), ("300 of 1,200", None), ("", None), (None, None), ("about half", None)],
)  # fmt: skip
def test_code_reads_the_sample_size_from_the_words_the_source_uses(
    written: str | None, count: int | None
) -> None:
    assert read_sample_size(written) == count


# --- RV-006: representativeness not stated ----------------------------------------------------


def test_unstated_sampling_scores_like_modelled_and_ranks_after_it() -> None:
    """Owner, BD-22: no credit and no penalty; below modelled, above non-representative."""
    assert REPRESENTATIVENESS_POINTS[R.NOT_STATED] == REPRESENTATIVENESS_POINTS[R.MODELLED]
    rank = REPRESENTATIVENESS_RANK
    assert rank[R.MODELLED] < rank[R.NOT_STATED] < rank[R.NON_REPRESENTATIVE]
    assert rank[R.NOT_APPLICABLE] == rank[R.NOT_STATED]
    unstated = claim(labels={"representativeness": R.NOT_STATED})
    assert (
        badges(unstated, [GeographyLevel.CITY_WIDE], date(2025, 6, 1), badge_params()).main is None
    )


# --- RV-017: the context city is not evidence -----------------------------------------------


def test_the_area_must_be_named_in_the_evidence() -> None:
    assert area_named("Halden Bay", HALDEN, [QUOTE])
    assert area_named("Halden Bay City", HALDEN, ["the city of Halden Bay reported"])
    assert not area_named("Halden Bay", HALDEN, ["31.2% of adults had hypertension in 2024"])
    assert area_named("Port Ostra", HALDEN, ["| Port Ostra | 1,204 | 22.6 |"])
    assert not area_named("Port Ostra", HALDEN, ["| Kestrel Point | 1,204 | 22.6 |"])


# --- RV-028: subgroup and setting, not free-text wording --------------------------------------


def test_a_cascade_denominator_is_not_a_subgroup() -> None:
    cascade = claim(labels={"population_group": "adults with hypertension"})
    assert (
        badges(cascade, [GeographyLevel.CITY_WIDE], date(2025, 6, 1), badge_params()).main is None
    )


@pytest.mark.parametrize(
    "overrides",
    [{"population_subgroup": True}, {"setting": Setting.HEALTH_FACILITY},
     {"setting": Setting.SCHOOL}, {"setting": Setting.WORKPLACE}],
)  # fmt: skip
def test_a_subgroup_or_a_narrow_setting_is_not_city_level(overrides: dict[str, object]) -> None:
    narrowed = claim(labels=overrides)
    main = badges(narrowed, [GeographyLevel.CITY_WIDE], date(2025, 6, 1), badge_params()).main
    assert main is Badge.NOT_CITY_LEVEL


def test_settings_stored_as_free_text_are_read_into_the_vocabulary() -> None:
    assert labels(setting="Hospital").setting is Setting.HEALTH_FACILITY
    assert labels(setting="primary health care clinics").setting is Setting.OTHER
    assert labels(setting=None).setting is None


def test_the_flag_for_a_cleared_label_exists() -> None:
    assert ClaimFlag.LABEL_NOT_LOCATED.value == "label_not_located"


# --- RV-007, RV-099: publication dates from metadata only; precision; language -------------


BODY = "<p>" + "In 2019, 31 % of adults in Halden Bay had hypertension. " * 8 + "</p>"


def page(head: str, lang: str = "") -> bytes:
    return (f"<html{lang}><head>{head}<title>Heart health</title></head><body><article>"
            f"{BODY}<p>Copyright 2014-2023 Halden Bay Health Office.</p></article></body></html>"
            ).encode()  # fmt: skip


def test_a_year_in_the_body_text_is_never_a_publication_date() -> None:
    doc = DocumentParser().parse_html(page(""), "http://health.halden-bay.test/a")
    assert (doc.published_date, doc.published_precision) == (None, None)


def test_a_metadata_date_keeps_the_precision_it_was_written_with() -> None:
    parser = DocumentParser()
    day = parser.parse_html(page('<meta name="date" content="2025-06-01">'), "http://h.test/a")
    assert (day.published_date, day.published_precision) == (date(2025, 6, 1), DatePrecision.DAY)


def test_the_page_language_comes_from_its_html_lang() -> None:
    doc = DocumentParser().parse_html(page("", ' lang="nb-NO"'), "http://h.test/a")
    assert doc.language == "nb"
