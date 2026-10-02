"""Threshold coding (LLD-2 §4.3) and the comparability key (§4.4)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.workflow.rules.comparability import comparability_key, differing_parts, key_gaps, slug
from app.workflow.rules.thresholds import ThresholdRule, threshold_code, threshold_table
from tests.unit.builders import labels, statistic

THRESHOLDS = Path(__file__).resolve().parents[2] / "reference" / "thresholds.yaml"


@pytest.fixture(scope="module")
def table() -> tuple[ThresholdRule, ...]:
    return threshold_table(yaml.safe_load(THRESHOLDS.read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("case_definition", "code"),
    [
        ("SBP>=140 and/or DBP>=90, or on medication", "bp_140_90"),
        ("Systolic ≥ 140 mmHg or diastolic ≥ 90 mmHg", "bp_140_90"),
        ("Blood pressure of 140/90 mmHg or above", "bp_140_90"),
        ("SBP ≥130 or DBP ≥80 (ACC/AHA 2017)", "bp_130_80"),
        ("BP 130 / 80 or higher", "bp_130_80"),
        ("Fasting plasma glucose >= 7.0 mmol/L or on treatment", "fpg_7_0"),
        ("FPG ≥ 126 mg/dL", "fpg_7_0"),
        ("Glucemia en ayunas ≥ 7,0 mmol/l", "fpg_7_0"),
        ("Self-reported diagnosis by a doctor", None),
        (None, None),
    ],
)
def test_threshold_codes(
    table: tuple[ThresholdRule, ...], case_definition: str | None, code: str | None
) -> None:
    assert threshold_code(case_definition, table) == code


def test_threshold_table_refuses_entries_without_patterns() -> None:
    with pytest.raises(ValueError, match="needs a code and patterns"):
        threshold_table([{"code": "bp_140_90", "patterns": []}])


def test_comparable_figures_share_a_key() -> None:
    a = comparability_key(statistic("clm_a"), labels())
    b = comparability_key(statistic("clm_b", "29.8"), labels(geography_name="HALDEN BAY"))

    assert a is not None
    assert a == b


def test_140_90_and_130_80_never_share_a_key() -> None:
    """F7: different thresholds measure different things."""
    a = comparability_key(statistic(), labels(threshold_code="bp_140_90"))
    b = comparability_key(statistic(), labels(threshold_code="bp_130_80"))

    assert a is not None
    assert b is not None
    assert a != b


def test_adults_18_plus_and_30_to_79_never_share_a_key() -> None:
    adults = comparability_key(statistic(), labels(population_age_min=18, population_age_max=None))
    band = comparability_key(statistic(), labels())

    assert adults != band
    assert adults is None  # open-ended band: age band not fully stated


def test_unknown_age_band_gives_no_key() -> None:
    stat, lab = statistic(), labels(population_age_min=None, population_age_max=None)

    assert comparability_key(stat, lab) is None
    assert "age band not fully stated" in key_gaps(stat, lab)


def test_age_zero_is_a_stated_bound() -> None:
    assert comparability_key(statistic(), labels(population_age_min=0, population_age_max=17))


@pytest.mark.parametrize(
    ("stat_overrides", "label_overrides", "gap"),
    [
        ({"indicator_code": "OTHER"}, {}, "indicator is OTHER, never compared"),
        ({"value_num": None}, {}, "no single parsed value"),
        ({}, {"threshold_code": None}, "threshold not stated or not recognised"),
    ],
)
def test_no_key_when_a_part_is_missing(
    stat_overrides: dict[str, Any], label_overrides: dict[str, Any], gap: str
) -> None:
    stat, lab = statistic(**stat_overrides), labels(**label_overrides)

    assert comparability_key(stat, lab) is None
    assert gap in key_gaps(stat, lab)


def test_differing_parts_name_what_separates_two_figures() -> None:
    a = (statistic(), labels())
    b = (statistic(), labels(threshold_code="bp_130_80", population_age_min=18))

    assert differing_parts(a, b) == ["threshold", "age band"]


def test_slug_folds_case_diacritics_and_punctuation() -> None:
    assert slug("  Halden-Báy (city) ") == "halden-bay-city"
