"""Wave 0 rules (LLD-2 §13, BD-13): record selection, the canonical line, code
verification, and region matching for sub-national records. Fictional data only."""

import pytest

from app.domain.models import SourceIndicator
from app.domain.vocab import GeographyLevel, MeasureType
from app.ports.structured import StructuredRecord
from app.workflow.rules.region_match import region_matches
from app.workflow.rules.wave0 import age_text, canonical_line, code_check, select_record

CONTROL = SourceIndicator(
    code="NCD_HYP_CONTROL_A", slot="S04", measure=MeasureType.CASCADE_CONTROL, age=(30, 79),
    sex="SEX_BTSX",
)  # fmt: skip
DIABETES = SourceIndicator(
    code="NCD_DIABETES_PREVALENCE_AGESTD",
    slot="S05",
    measure=MeasureType.MEASURED_PREVALENCE,
    age=(18, None),
    age_group="AGEGROUP_YEARS18-PLUS",
    sex="SEX_BTSX",
)


def rec(
    year: int,
    value: str,
    sex: str = "SEX_BTSX",
    area: str = "XNV",
    age: str | None = None,
    code: str = "NCD_HYP_CONTROL_A",
) -> StructuredRecord:
    return StructuredRecord(
        indicator_code=code,
        area_code=area,
        year=year,
        sex=sex,
        age_group=age,
        value_as_written=value,
        display=f"{value} [1.0-2.0]",
    )


RECORDS = [
    rec(2018, "13.9"),
    rec(2019, "14.8"),
    rec(2019, "18.5", sex="SEX_FMLE"),
    rec(2020, "99.9", area="OTH"),
]


def test_latest_record_for_the_country_and_both_sexes() -> None:
    chosen = select_record(RECORDS, CONTROL, "XNV")
    assert chosen is not None
    assert (chosen.year, chosen.value_as_written) == (2019, "14.8")


def test_age_group_is_required_when_the_indicator_has_one() -> None:
    code = "NCD_DIABETES_PREVALENCE_AGESTD"
    records = [
        rec(2022, "15.2", age="AGEGROUP_YEARS30-PLUS", code=code),
        rec(2022, "11.4", age="AGEGROUP_YEARS18-PLUS", code=code),
    ]
    chosen = select_record(records, DIABETES, "XNV")
    assert chosen is not None
    assert chosen.value_as_written == "11.4"


def test_no_record_for_the_country_selects_nothing() -> None:
    assert select_record(RECORDS, CONTROL, "ZZZ") is None


def test_canonical_line() -> None:
    assert canonical_line(rec(2019, "14.8"), CONTROL) == (
        "NCD_HYP_CONTROL_A | XNV | 2019 | SEX_BTSX | 30-79 | 14.8 [1.0-2.0]"
    )
    assert age_text(DIABETES) == "18+"
    assert age_text(SourceIndicator(code="SP.POP.TOTL")) == "all ages"


def test_code_check_passes_when_the_reread_record_is_the_same() -> None:
    line = canonical_line(rec(2019, "14.8"), CONTROL)
    result = code_check(line, "14.8", RECORDS, CONTROL, "XNV")
    assert result.matched
    assert "14.8" in result.reason


def test_an_altered_value_fails_the_code_check() -> None:
    """LLD-2 §13 test: the stored record no longer holds the claimed value."""
    line = canonical_line(rec(2019, "14.8"), CONTROL)
    altered = [rec(2018, "13.9"), rec(2019, "41.8")]
    result = code_check(line, "14.8", altered, CONTROL, "XNV")
    assert not result.matched
    assert len(result.reason) <= 400


def test_a_changed_claim_value_fails_the_code_check() -> None:
    line = canonical_line(rec(2019, "14.8"), CONTROL)
    assert not code_check(line, "15.0", RECORDS, CONTROL, "XNV").matched


def test_a_response_with_no_record_fails_the_code_check() -> None:
    line = canonical_line(rec(2019, "14.8"), CONTROL)
    assert not code_check(line, "14.8", [], CONTROL, "XNV").matched


# --- sub-national records: normalised name match or an approved alias, never a guess ---


@pytest.mark.parametrize(
    ("provider_region", "admin1", "aliases", "matches"),
    [
        ("West Coast", "West Coast", {}, True),
        ("West Coast Region", "West Coast", {}, True),
        ("WEST COAST province", "West Coast", {}, True),
        ("Inland", "West Coast", {}, False),  # an unmatched region is skipped
        ("Westcoast", "West Coast", {}, False),  # near misses are not guessed
        ("Coastal West", "West Coast", {"West Coast": ["Coastal West"]}, True),
        ("West Coast", None, {}, False),
        ("Region", "West Coast", {}, False),  # nothing left after generic words
    ],
)
def test_region_matching(
    provider_region: str, admin1: str | None, aliases: dict[str, list[str]], matches: bool
) -> None:
    assert region_matches(provider_region, admin1, aliases) is matches


# --- BD-34: never guessed (code review RV-033, RV-082) -----------------------------------------


def test_only_the_registry_indicator_is_used() -> None:
    other = [rec(2021, "40.0", code="NCD_HYP_DIAGNOSIS_A"), rec(2019, "14.8")]
    chosen = select_record(other, CONTROL, "XNV")
    assert chosen is not None
    assert chosen.year == 2019


def test_two_records_for_the_latest_year_give_none() -> None:
    """Dimensions the registry does not name (urban and rural, say) are never picked."""
    tied = [rec(2021, "14.8"), rec(2021, "16.2"), rec(2019, "13.9")]
    assert select_record(tied, CONTROL, "XNV") is None


def test_a_latest_year_without_a_value_never_falls_back_to_an_older_one() -> None:
    gap = [rec(2021, ""), rec(2019, "13.9")]
    assert select_record(gap, CONTROL, "XNV") is None


def test_the_registry_refuses_claim_indicators_without_labels() -> None:
    from pydantic import ValidationError

    from app.domain.models import SourceProvider

    with pytest.raises(ValidationError, match="needs a measure and a sex code"):
        SourceIndicator(code="NCD_HYP_CONTROL_A", slot="S04", sex="SEX_BTSX")
    SourceIndicator(code="SP.POP.TOTL")  # a source only: no slot, no labels needed
    with pytest.raises(ValidationError, match="never city-level"):
        SourceProvider(
            provider="x", adapter="who_gho", publisher_class="multilateral",
            publisher_name="X", attribution="X", geography=GeographyLevel.CITY_WIDE,
            indicators={},
        )  # fmt: skip
