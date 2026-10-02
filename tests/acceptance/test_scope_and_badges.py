"""Scope and badge acceptance tests at rule level (LLD-4 §11). AT-13 and AT-14 join this
file with the tasks that build them; the run-level versions follow with D2-3."""

from datetime import date

from app.domain.badges import badges
from app.domain.vocab import (
    Badge,
    ClaimFlag,
    ClaimKind,
    ClaimStatus,
    ConsistencyOutcome,
    MeasureType,
    PublisherClass,
)
from app.workflow.rules.comparability import comparability_key
from app.workflow.rules.consistency import StatisticFact, check_statistic
from app.workflow.rules.labels import derive_flags
from app.workflow.rules.numbers import parse_value
from tests.unit.builders import (
    CITY_SLOT,
    TODAY,
    badge_params,
    claim,
    consistency_params,
    labels,
    statistic,
)

CONTROL_NO_BASE = {"measure_type": MeasureType.CASCADE_CONTROL, "denominator_stated": False,
                   "denominator_text": None}  # fmt: skip


def test_cascade_percentage_without_denominator_is_flagged_and_never_combined() -> None:
    """AT-21: given a care-cascade percentage with no stated denominator, then it is
    flagged and not combined with figures from other sources (R-33, R-34)."""
    no_base = labels(**CONTROL_NO_BASE)
    flags = derive_flags(ClaimKind.STATISTIC, no_base, "en", parse_value("18.4%"), badge_params())
    new = StatisticFact(
        claim("clm_new", source_id="src_1", labels=CONTROL_NO_BASE, flags=flags),
        statistic("clm_new", "18.4", indicator_code="HTN_CONTROL"),
        PublisherClass.NEWS,
    )
    other_source = StatisticFact(
        claim("clm_other", source_id="src_2", labels={"measure_type": MeasureType.CASCADE_CONTROL}),
        statistic("clm_other", "18.6", indicator_code="HTN_CONTROL"),
        PublisherClass.GOVERNMENT,
    )

    decision = check_statistic(new, [other_source], CITY_SLOT, consistency_params())

    assert ClaimFlag.DENOMINATOR_NOT_STATED in flags
    assert comparability_key(new.statistic, new.claim.labels) is None
    assert decision.outcome is ConsistencyOutcome.NOT_COMPARABLE  # not agrees: never combined
    assert "denominator not stated" in decision.reason
    assert decision.contested == ()


def test_figure_with_several_flags_shows_the_most_severe_badge_first() -> None:
    """AT-31: given a fact carrying several flags, then its main badge is the most severe
    by the fixed order and the others appear in the evidence panel (R-78)."""
    many = claim(
        status=ClaimStatus.CONTESTED,
        labels={
            "geography_level": "national",
            "geography_name": "Norvania",
            "reference_start": None,
            "reference_end": date(2015, 12, 31),
            "sample_size": 150,
        },
    )

    result = badges(many, CITY_SLOT, TODAY, badge_params())

    assert result.main is Badge.NOT_CITY_LEVEL
    assert result.others == (Badge.SOURCES_DISAGREE, Badge.OUTDATED, Badge.LIMITED_SAMPLE)


def test_severity_order_holds_without_the_top_badge() -> None:
    """AT-31: drop 'not city-level' and 'sources disagree' takes the main place."""
    contested_old = claim(
        status=ClaimStatus.CONTESTED,
        labels={"reference_start": None, "reference_end": date(2015, 12, 31)},
    )

    result = badges(contested_old, CITY_SLOT, TODAY, badge_params())

    assert (result.main, result.others) == (Badge.SOURCES_DISAGREE, (Badge.OUTDATED,))
