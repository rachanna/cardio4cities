"""Domain type validators (LLD-1 §2) and tunables matching LLD-2."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.domain.vocab import GEOGRAPHY_ORDER, Badge, GeographyLevel, PublisherClass
from tests.unit.builders import (
    badge_params,
    claim,
    confidence_params,
    consistency_params,
    labels,
    quote_params,
    replan_params,
    verify_params,
)


def test_reference_period_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="reference_start is after reference_end"):
        labels(reference_start=date(2025, 1, 1), reference_end=date(2024, 1, 1))


def test_age_band_must_be_ordered() -> None:
    with pytest.raises(ValidationError, match="population_age_min"):
        labels(population_age_min=80, population_age_max=30)


def test_span_must_be_non_empty() -> None:
    with pytest.raises(ValidationError, match="span_end"):
        claim(span_start=10, span_end=10)


def test_labels_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        labels(guessed_city="Halden Bay")


def test_orders_follow_the_design() -> None:
    assert GEOGRAPHY_ORDER[0] is GeographyLevel.CITY_WIDE
    assert GEOGRAPHY_ORDER[-1] is GeographyLevel.GLOBAL
    assert next(iter(Badge)) is Badge.NOT_CITY_LEVEL
    assert next(iter(PublisherClass)) is PublisherClass.GOVERNMENT


def test_shipped_tunables_match_lld2() -> None:
    """The [tunable] defaults in config are the values LLD-2 states."""
    assert (quote_params().min_words, quote_params().max_words) == (6, 60)
    assert consistency_params().agree_pp == Decimal("0.5")
    assert consistency_params().agree_rel == Decimal("0.02")
    assert (badge_params().stale_years, badge_params().stale_years_people) == (5, 2)
    assert badge_params().small_sample == 300
    assert confidence_params().recent_years == 5
    assert (replan_params().max_rounds, replan_params().max_rounds_wider_geo) == (2, 1)
    assert verify_params("deployed").max_claims_per_slot == 5
    assert verify_params("local").max_claims_per_slot == 3
