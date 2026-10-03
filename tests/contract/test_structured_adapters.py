"""Structured-data adapters (LLD-4 §8, BD-13, AT-35) against recorded responses. The
recordings keep the real response structure (spike S-2) with fictional values for
Norvania (XNV) only. Adapters are pure: they build URLs and parse bytes."""

from pathlib import Path

import pytest

from app.adapters.structured.who_gho import WhoGho
from app.adapters.structured.world_bank import WorldBank

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "structured"


def recorded(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_who_gho_url_filters_by_country() -> None:
    (url,) = WhoGho("https://ghoapi.example.test/api/").request_urls("NCD_HYP_CONTROL_A", "XNV", {})
    assert url == (
        "https://ghoapi.example.test/api/NCD_HYP_CONTROL_A?$filter=SpatialDim%20eq%20%27XNV%27"
    )


@pytest.mark.parametrize(
    ("code", "country"), [("X'; DROP", "XNV"), ("NCD_HYP", "xnv"), ("A", "XN")]
)
def test_who_gho_refuses_codes_that_did_not_come_from_reference_data(
    code: str, country: str
) -> None:
    with pytest.raises(ValueError, match="come from the registry"):
        WhoGho("https://ghoapi.example.test/api").request_urls(code, country, {})


def test_who_gho_parses_values_exactly_as_written_and_skips_empty_records() -> None:
    records = WhoGho("x").parse("NCD_HYP_CONTROL_A", recorded("who_gho_NCD_HYP_CONTROL_A_XNV.json"))
    assert len(records) == 4  # the record with no published value is skipped
    latest = next(r for r in records if r.year == 2019 and r.sex == "SEX_BTSX")
    assert latest.value_as_written == "14.8"
    assert latest.display == "14.8 [9.6-21.2]"
    assert (latest.indicator_code, latest.area_code, latest.age_group) == (
        "NCD_HYP_CONTROL_A",
        "XNV",
        None,
    )


def test_who_gho_keeps_the_age_dimension_when_the_indicator_has_one() -> None:
    records = WhoGho("x").parse(
        "NCD_DIABETES_PREVALENCE_AGESTD",
        recorded("who_gho_NCD_DIABETES_PREVALENCE_AGESTD_XNV.json"),
    )
    assert {r.age_group for r in records} == {
        "AGEGROUP_YEARS18-PLUS",
        "AGEGROUP_YEARS30-PLUS",
    }


def test_world_bank_url_and_parse() -> None:
    adapter = WorldBank("https://api.worldbank.example.test/v2")
    (url,) = adapter.request_urls("SP.POP.TOTL", "XNV", {})
    assert url == (
        "https://api.worldbank.example.test/v2/country/XNV/indicator/SP.POP.TOTL"
        "?format=json&per_page=100&mrv=10"
    )
    records = adapter.parse("SP.POP.TOTL", recorded("world_bank_SP.POP.TOTL_XNV.json"))
    assert [(r.year, r.value_as_written) for r in records] == [(2025, "5123456"), (2024, "5098765")]
    assert {r.sex for r in records} == {"total"}


@pytest.mark.parametrize("raw", [b"<html>not json</html>", b'{"unexpected": 1}', b"\xff\xfe"])
def test_unparseable_responses_raise_value_error(raw: bytes) -> None:
    with pytest.raises(ValueError, match="not a GHO OData response"):
        WhoGho("x").parse("NCD_HYP_CONTROL_A", raw)
    with pytest.raises(ValueError, match="not a World Bank API response"):
        WorldBank("x").parse("SP.POP.TOTL", raw)
