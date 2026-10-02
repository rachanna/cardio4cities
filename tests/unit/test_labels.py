"""Reference-period rule (LLD-1 §2.3) and derived flags."""

from datetime import date

from app.domain.vocab import ClaimFlag, ClaimKind, DatePrecision, MeasureType, PeriodType
from app.workflow.rules.labels import apply_reference_period_rule, derive_flags
from app.workflow.rules.numbers import parse_value
from tests.unit.builders import badge_params, labels


def test_no_stated_period_uses_publication_date_as_proxy() -> None:
    unstated = labels(reference_start=None, reference_end=None, reference_precision=None)

    result = apply_reference_period_rule(unstated, date(2025, 3, 1), DatePrecision.MONTH)

    assert result.period_type is PeriodType.PUBLICATION_DATE_PROXY
    assert (result.reference_end, result.reference_precision) == (date(2025, 3, 1), "month")


def test_stated_period_is_left_alone() -> None:
    stated = labels()

    assert apply_reference_period_rule(stated, date(2025, 3, 1), DatePrecision.DAY) == stated


def _flags(
    kind: ClaimKind = ClaimKind.STATISTIC, value: str = "31.2%", **overrides: object
) -> frozenset[ClaimFlag]:
    return derive_flags(kind, labels(**overrides), "en", parse_value(value), badge_params())


def test_complete_statistic_has_no_flags() -> None:
    assert _flags() == frozenset()


def test_missing_denominator_on_a_cascade_measure_is_flagged() -> None:
    flags = _flags(measure_type=MeasureType.CASCADE_CONTROL, denominator_stated=False)

    assert ClaimFlag.DENOMINATOR_NOT_STATED in flags


def test_missing_denominator_on_a_count_is_not_flagged() -> None:
    flags = _flags(measure_type=MeasureType.POPULATION_COUNT, denominator_stated=False)

    assert ClaimFlag.DENOMINATOR_NOT_STATED not in flags


def test_each_flag_from_its_label() -> None:
    proxy = labels(period_type=PeriodType.PUBLICATION_DATE_PROXY)
    flags = derive_flags(
        ClaimKind.STATISTIC, proxy, "es", parse_value("about a third"), badge_params()
    )

    assert flags == {ClaimFlag.PERIOD_NOT_STATED, ClaimFlag.TRANSLATED, ClaimFlag.VALUE_UNPARSED}
    assert ClaimFlag.SMALL_SAMPLE in _flags(sample_size=120)
    assert ClaimFlag.NON_REPRESENTATIVE in _flags(representativeness="non_representative")
    assert ClaimFlag.SETTING_NOT_STATED in _flags(setting=None)


def test_statement_claims_skip_statistic_flags() -> None:
    assert _flags(kind=ClaimKind.STATEMENT, setting=None, denominator_stated=False) == frozenset()
