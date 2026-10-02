"""Ranking (LLD-2 §5.2-5.3), confidence (§7) and badges (§8)."""

from datetime import date

import pytest

from app.domain.badges import Badges, badges, most_severe
from app.domain.confidence import confidence
from app.domain.models import Verdict
from app.domain.ranking import Candidate, geography_distance, ranked, select_for_verification
from app.domain.vocab import (
    Badge,
    ClaimFlag,
    ClaimKind,
    ClaimStatus,
    ConfidenceLabel,
    GeographyLevel,
    PublisherClass,
    RelationType,
)
from tests.unit.builders import (
    CITY_SLOT,
    TODAY,
    badge_params,
    claim,
    confidence_params,
    verify_params,
)

GOV, MULTI, NEWS = PublisherClass.GOVERNMENT, PublisherClass.MULTILATERAL, PublisherClass.NEWS


def _verdict(**overrides: object) -> Verdict:
    values: dict[str, object] = {
        "claim_id": "clm_a",
        "label": "supported",
        "rationale": "The passage states the figure for the city.",
        "scope_verified": True,
        "period_verified": True,
        "verifier_model": "test-checker",
        "verifier_family": "openai",
        "prompt_version": "checker@v1+00000000",
    }
    values.update(overrides)
    return Verdict.model_validate(values)


# --- ranking ------------------------------------------------------------------------


def test_ranking_order_tier_then_representativeness_then_fit_then_recency_then_id() -> None:
    news = Candidate(claim("clm_1"), NEWS)
    gov_modelled = Candidate(claim("clm_2", labels={"representativeness": "modelled"}), GOV)
    gov_national = Candidate(claim("clm_3", labels={"geography_level": "national"}), GOV)
    gov_old = Candidate(
        claim("clm_4", labels={"reference_start": None, "reference_end": date(2015, 1, 1)}), GOV
    )
    gov_new = Candidate(claim("clm_5"), GOV)
    gov_new_twin = Candidate(claim("clm_6"), MULTI)

    order = [
        c.claim.claim_id
        for c in ranked(
            [news, gov_modelled, gov_national, gov_old, gov_new, gov_new_twin], CITY_SLOT
        )
    ]

    assert order == ["clm_5", "clm_6", "clm_4", "clm_3", "clm_2", "clm_1"]


def test_undated_claims_rank_last_on_recency() -> None:
    undated = Candidate(
        claim("clm_1", labels={"reference_start": None, "reference_end": None}), GOV
    )
    dated = Candidate(claim("clm_2"), GOV)

    assert [c.claim.claim_id for c in ranked([undated, dated], CITY_SLOT)] == ["clm_2", "clm_1"]


def test_geography_distance_to_nearest_accepted_level() -> None:
    accepted = [GeographyLevel.CITY_WIDE, GeographyLevel.METRO_REGION]

    assert geography_distance(GeographyLevel.METRO_REGION, accepted) == 0
    assert geography_distance(GeographyLevel.DISTRICT, accepted) == 1
    assert geography_distance(GeographyLevel.NATIONAL, accepted) == 3


def test_verification_cap_keeps_the_top_n() -> None:
    candidates = [Candidate(claim(f"clm_{n}"), NEWS if n % 2 else GOV) for n in range(8)]

    chosen = select_for_verification(candidates, CITY_SLOT, verify_params("deployed"))

    assert len(chosen) == 5
    assert {c.publisher_class for c in chosen[:4]} == {GOV}


# --- confidence -----------------------------------------------------------------------


def test_who_style_national_modelled_figure_for_a_city_slot_is_medium() -> None:
    """LLD-2 §7: 2 + 1 + 0 + 1 + 1 + 1 = 6."""
    national = claim(labels={"geography_level": "national", "geography_name": "Norvania",
                             "representativeness": "modelled"})  # fmt: skip

    result = confidence(national, MULTI, CITY_SLOT, _verdict(), TODAY, confidence_params())

    assert (result.points, result.label) == (6, ConfidenceLabel.MEDIUM)
    assert [r.component for r in result.reasons if r.points == 0] == ["geography_fit"]


def test_recent_verified_government_city_survey_is_high() -> None:
    result = confidence(claim(), GOV, CITY_SLOT, _verdict(), TODAY, confidence_params())

    assert (result.points, result.label) == (9, ConfidenceLabel.HIGH)


def test_low_at_three_points_or_fewer() -> None:
    weak = claim(labels={"geography_level": "national", "representativeness": "non_representative",
                         "reference_start": None, "reference_end": date(2010, 1, 1),
                         "denominator_stated": False})  # fmt: skip

    result = confidence(weak, NEWS, CITY_SLOT, None, TODAY, confidence_params())

    assert (result.points, result.label) == (0, ConfidenceLabel.LOW)


def test_same_family_fallback_caps_at_medium() -> None:
    result = confidence(
        claim(), GOV, CITY_SLOT, _verdict(fallback_used=True), TODAY, confidence_params()
    )

    assert (result.points, result.label) == (9, ConfidenceLabel.MEDIUM)
    assert result.capped_by == "same-family fallback checker"


def test_period_not_stated_caps_at_medium() -> None:
    proxy = claim(flags=frozenset({ClaimFlag.PERIOD_NOT_STATED}))

    result = confidence(proxy, GOV, CITY_SLOT, _verdict(), TODAY, confidence_params())

    assert result.label is ConfidenceLabel.MEDIUM


def test_confidence_only_for_shown_claims() -> None:
    with pytest.raises(ValueError, match="supported or contested"):
        confidence(
            claim(status=ClaimStatus.REFUTED), GOV, CITY_SLOT, None, TODAY, confidence_params()
        )


# --- badges -----------------------------------------------------------------------


def test_national_and_old_figure_is_not_city_level_first_then_outdated() -> None:
    """LLD-2 §8 test."""
    old_national = claim(
        labels={
            "geography_level": "national",
            "geography_name": "Norvania",
            "reference_start": None,
            "reference_end": date(2016, 6, 30),
        }
    )

    assert badges(old_national, CITY_SLOT, TODAY, badge_params()) == Badges(
        Badge.NOT_CITY_LEVEL, (Badge.OUTDATED,)
    )


@pytest.mark.parametrize(
    ("label_overrides", "badge"),
    [
        ({"population_group": "university staff"}, Badge.NOT_CITY_LEVEL),
        ({"setting": "Hospital"}, Badge.NOT_CITY_LEVEL),
        ({"representativeness": "non_representative"}, Badge.LIMITED_SAMPLE),
        ({"sample_size": 120}, Badge.LIMITED_SAMPLE),
    ],
)
def test_each_badge_condition(label_overrides: dict[str, object], badge: Badge) -> None:
    assert badges(claim(labels=label_overrides), CITY_SLOT, TODAY, badge_params()).main is badge


def test_general_population_wording_is_city_level() -> None:
    for group in ("adults", "All ages", "general population"):
        assert (
            badges(claim(labels={"population_group": group}), CITY_SLOT, TODAY, badge_params()).main
            is None
        )


def test_contested_claim_says_sources_disagree() -> None:
    contested = claim(status=ClaimStatus.CONTESTED)

    assert badges(contested, CITY_SLOT, TODAY, badge_params()).main is Badge.SOURCES_DISAGREE


def test_leads_relations_go_stale_after_two_years_others_never() -> None:
    three_years = claim(
        kind=ClaimKind.RELATION,
        labels={"reference_start": None, "reference_end": date(2023, 6, 1)},
    )

    leads = badges(three_years, CITY_SLOT, TODAY, badge_params(), RelationType.LEADS)
    governs = badges(three_years, CITY_SLOT, TODAY, badge_params(), RelationType.GOVERNS)

    assert leads.main is Badge.OUTDATED
    assert governs.main is None


def test_sentence_takes_the_most_severe_main_badge() -> None:
    assert (
        most_severe([Badge.LIMITED_SAMPLE, None, Badge.SOURCES_DISAGREE]) is Badge.SOURCES_DISAGREE
    )
    assert most_severe([None, None]) is None
