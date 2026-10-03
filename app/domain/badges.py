"""Badges (LLD-2 §8, R-78, AT-31): one main badge per fact, by fixed severity;
the rest are shown in the evidence panel. Computed at read time."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.dates import years_before
from app.domain.geography import effective_level
from app.domain.models import Claim
from app.domain.params import BadgeParams
from app.domain.vocab import (
    Badge,
    ClaimKind,
    ClaimStatus,
    GeographyLevel,
    RelationType,
    Representativeness,
)

SEVERITY: tuple[Badge, ...] = tuple(Badge)  # declaration order, most severe first
GENERAL_POPULATIONS = frozenset({"adults", "all ages", "general population"})
NARROW_SETTINGS = frozenset({"hospital", "clinic", "workplace", "school"})


@dataclass(frozen=True)
class Badges:
    main: Badge | None
    others: tuple[Badge, ...]


def _is_not_city_level(claim: Claim, accepted: Sequence[GeographyLevel]) -> bool:
    labels = claim.labels
    if effective_level(claim) not in accepted:
        return True
    group = (labels.population_group or "").strip().casefold()
    if group and group not in GENERAL_POPULATIONS:
        return True
    return (labels.setting or "").strip().casefold() in NARROW_SETTINGS


def _is_outdated(
    claim: Claim, relation_type: RelationType | None, today: date, params: BadgeParams
) -> bool:
    end = claim.labels.reference_end
    if end is None:
        return False
    if claim.kind is ClaimKind.RELATION:
        if relation_type is not RelationType.LEADS:
            return False
        return end < years_before(today, params.stale_years_people)
    return end < years_before(today, params.stale_years)


def _is_limited_sample(claim: Claim, params: BadgeParams) -> bool:
    labels = claim.labels
    if labels.representativeness is Representativeness.NON_REPRESENTATIVE:
        return True
    return labels.sample_size is not None and labels.sample_size < params.small_sample


def badges(
    claim: Claim,
    accepted: Sequence[GeographyLevel],
    today: date,
    params: BadgeParams,
    relation_type: RelationType | None = None,
) -> Badges:
    """`accepted` is the slot's accepted levels; `relation_type` for relation claims."""
    holds = {
        Badge.NOT_CITY_LEVEL: _is_not_city_level(claim, accepted),
        Badge.SOURCES_DISAGREE: claim.status is ClaimStatus.CONTESTED,
        Badge.OUTDATED: _is_outdated(claim, relation_type, today, params),
        Badge.LIMITED_SAMPLE: _is_limited_sample(claim, params),
    }
    found = [badge for badge in SEVERITY if holds[badge]]
    return Badges(main=found[0] if found else None, others=tuple(found[1:]))


def most_severe(main_badges: Iterable[Badge | None]) -> Badge | None:
    """The main badge of a sentence citing several claims."""
    present = [b for b in main_badges if b is not None]
    return min(present, key=SEVERITY.index) if present else None
