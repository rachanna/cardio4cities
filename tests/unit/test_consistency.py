"""Consistency (LLD-2 §5.4 statistics, §5.5 relations; BD-06 for relation ordering)."""

from datetime import date

from app.domain.vocab import (
    ClaimKind,
    ClaimStatus,
    ConsistencyOutcome,
    PublisherClass,
    RelationType,
)
from app.workflow.rules.consistency import (
    RelationFact,
    StatisticFact,
    check_relation,
    check_statistic,
)
from tests.unit.builders import CITY_SLOT, claim, consistency_params, relation, statistic

GOV, NEWS = PublisherClass.GOVERNMENT, PublisherClass.NEWS


def _stat(
    claim_id: str, value: str, publisher: PublisherClass = GOV, **labels: object
) -> StatisticFact:
    return StatisticFact(claim(claim_id, labels=labels), statistic(claim_id, value), publisher)


def _check(new: StatisticFact, *others: StatisticFact) -> ConsistencyOutcome:
    return check_statistic(new, others, CITY_SLOT, consistency_params()).outcome


def test_figures_0_3_points_apart_agree() -> None:
    assert _check(_stat("clm_b", "31.5"), _stat("clm_a", "31.2")) is ConsistencyOutcome.AGREES


def test_figures_4_points_apart_are_contested_with_headline_by_tier() -> None:
    new, old = _stat("clm_b", "35.2", NEWS), _stat("clm_a", "31.2", GOV)

    decision = check_statistic(new, [old], CITY_SLOT, consistency_params())

    assert decision.outcome is ConsistencyOutcome.CONFLICTS
    (pair,) = decision.contested
    assert (pair.claim_a, pair.claim_b, pair.headline_claim) == ("clm_a", "clm_b", "clm_a")


def test_different_survey_years_are_a_time_series_not_a_conflict() -> None:
    old = _stat("clm_a", "27.0", reference_start=date(2019, 1, 1), reference_end=date(2019, 12, 31))

    assert _check(_stat("clm_b", "31.2"), old) is ConsistencyOutcome.NOVEL


def test_140_90_against_130_80_is_not_comparable() -> None:
    other = _stat("clm_a", "45.0", threshold_code="bp_130_80")

    decision = check_statistic(_stat("clm_b", "31.2"), [other], CITY_SLOT, consistency_params())

    assert decision.outcome is ConsistencyOutcome.NOVEL  # different keys never meet
    assert decision.compared_with == ()


def test_figure_without_key_is_not_comparable_and_says_why() -> None:
    no_age = _stat("clm_b", "31.2", population_age_min=None)

    decision = check_statistic(no_age, [_stat("clm_a", "31.0")], CITY_SLOT, consistency_params())

    assert decision.outcome is ConsistencyOutcome.NOT_COMPARABLE
    assert decision.compared_with == ("clm_a",)
    assert "age band" in decision.reason


def test_only_supported_or_contested_figures_count() -> None:
    refuted = StatisticFact(
        claim("clm_a", status=ClaimStatus.REFUTED), statistic("clm_a", "40.0"), GOV
    )

    assert _check(_stat("clm_b", "31.2"), refuted) is ConsistencyOutcome.NOVEL


def test_relative_tolerance_for_non_percent_values() -> None:
    a = StatisticFact(
        claim("clm_a"), statistic("clm_a", "1000", unit="count", value_as_written="1,000"), GOV
    )
    close = StatisticFact(
        claim("clm_b"), statistic("clm_b", "1015", unit="count", value_as_written="1,015"), GOV
    )
    far = StatisticFact(
        claim("clm_c"), statistic("clm_c", "1100", unit="count", value_as_written="1,100"), GOV
    )

    assert _check(close, a) is ConsistencyOutcome.AGREES
    assert _check(far, a) is ConsistencyOutcome.CONFLICTS


# --- relations ------------------------------------------------------------------------


def _rel(
    claim_id: str,
    subject: str,
    start: date | None,
    relation_type: RelationType = RelationType.GOVERNS,
    valid_to: date | None = None,
    proxy: bool = False,
) -> RelationFact:
    return RelationFact(
        claim(claim_id, kind=ClaimKind.RELATION),
        relation(claim_id, subject, "ent_halden_bay", relation_type, start, valid_to, proxy),
        GOV,
    )


def test_newer_governs_with_later_valid_from_supersedes() -> None:
    old = _rel("clm_a", "ent_directorate", date(2018, 1, 1))

    decision = check_relation(_rel("clm_b", "ent_authority", date(2024, 7, 1)), [old], CITY_SLOT)

    assert decision.supersedes == ("clm_a",)
    assert decision.contested == ()


def test_two_governs_from_the_same_year_are_contested() -> None:
    old = _rel("clm_a", "ent_directorate", date(2024, 2, 1))

    decision = check_relation(_rel("clm_b", "ent_authority", date(2024, 9, 1)), [old], CITY_SLOT)

    assert decision.outcome is ConsistencyOutcome.CONFLICTS
    assert decision.contested[0].claim_a == "clm_a"


def test_older_claim_is_kept_as_history() -> None:
    current = _rel("clm_a", "ent_authority", date(2024, 7, 1))

    decision = check_relation(
        _rel("clm_b", "ent_directorate", date(2018, 1, 1)), [current], CITY_SLOT
    )

    assert decision.new_is_history
    assert decision.supersedes == ()


def test_proxy_dates_within_twelve_months_cannot_order_two_edges() -> None:
    old = _rel("clm_a", "ent_directorate", date(2023, 11, 1), proxy=True)

    decision = check_relation(_rel("clm_b", "ent_authority", date(2024, 6, 1)), [old], CITY_SLOT)

    assert decision.outcome is ConsistencyOutcome.CONFLICTS


def test_missing_start_date_is_contested_not_silently_replaced() -> None:
    old = _rel("clm_a", "ent_directorate", None)

    decision = check_relation(_rel("clm_b", "ent_authority", date(2024, 6, 1)), [old], CITY_SLOT)

    assert decision.outcome is ConsistencyOutcome.CONFLICTS


def test_ended_edge_is_superseded_by_a_later_start() -> None:
    ended = _rel("clm_a", "ent_directorate", date(2024, 1, 1), valid_to=date(2024, 3, 31))

    decision = check_relation(_rel("clm_b", "ent_authority", date(2024, 4, 1)), [ended], CITY_SLOT)

    assert decision.supersedes == ("clm_a",)


def test_same_governing_body_agrees() -> None:
    old = _rel("clm_a", "ent_directorate", date(2020, 1, 1))

    decision = check_relation(_rel("clm_b", "ent_directorate", date(2024, 1, 1)), [old], CITY_SLOT)

    assert decision.outcome is ConsistencyOutcome.AGREES


def test_leads_follows_the_same_rule() -> None:
    old = _rel("clm_a", "ent_person_a", date(2019, 1, 1), relation_type=RelationType.LEADS)

    decision = check_relation(
        _rel("clm_b", "ent_person_b", date(2025, 1, 1), relation_type=RelationType.LEADS),
        [old],
        CITY_SLOT,
    )

    assert decision.supersedes == ("clm_a",)


def test_other_relation_types_agree_or_are_novel() -> None:
    runs = _rel("clm_a", "ent_ngo", None, relation_type=RelationType.RUNS)

    same = check_relation(
        _rel("clm_b", "ent_ngo", None, relation_type=RelationType.RUNS), [runs], CITY_SLOT
    )
    other = check_relation(
        _rel("clm_c", "ent_clinic", None, relation_type=RelationType.RUNS), [runs], CITY_SLOT
    )

    assert same.outcome is ConsistencyOutcome.AGREES
    assert other.outcome is ConsistencyOutcome.NOVEL
