"""Ranking key used wherever a "best" claim is chosen (LLD-2 §5.2), and the
per-slot verification cap (§5.3)."""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from app.domain.geography import effective_level
from app.domain.models import Claim
from app.domain.params import VerifyParams
from app.domain.vocab import GEOGRAPHY_ORDER, GeographyLevel, PublisherClass, Representativeness

SOURCE_TIER: dict[PublisherClass, int] = {
    PublisherClass.GOVERNMENT: 0,
    PublisherClass.MULTILATERAL: 0,
    PublisherClass.ACADEMIC: 1,
    PublisherClass.NGO: 2,
    PublisherClass.NEWS: 3,
    PublisherClass.OTHER: 4,
}

REPRESENTATIVENESS_RANK: dict[Representativeness, int] = {
    Representativeness.CENSUS: 0,
    Representativeness.REPRESENTATIVE_SAMPLE: 1,
    Representativeness.MODELLED: 2,
    # Unknown sampling ranks after modelled, before non-representative (owner, BD-22)
    Representativeness.NOT_STATED: 3,
    Representativeness.NOT_APPLICABLE: 3,
    Representativeness.NON_REPRESENTATIVE: 4,
}


@dataclass(frozen=True)
class Candidate:
    """A claim with the source class needed to rank it."""

    claim: Claim
    publisher_class: PublisherClass


def geography_distance(level: GeographyLevel, accepted: Iterable[GeographyLevel]) -> int:
    """0 when the level is accepted, else steps to the nearest accepted level."""
    accepted = list(accepted)
    if level in accepted:
        return 0
    position = GEOGRAPHY_ORDER.index(level)
    return min(abs(position - GEOGRAPHY_ORDER.index(a)) for a in accepted)


def rank_key(
    candidate: Candidate, accepted: Sequence[GeographyLevel]
) -> tuple[int, int, int, int, int, str]:
    """Sort ascending; the first claim wins. Geography comes first (owner, BD-36): a
    figure for the city is checked and preferred before any wider-area one, whatever
    its source; wider-area figures still show, with their badge."""
    labels = candidate.claim.labels
    end = labels.reference_end
    return (
        geography_distance(effective_level(candidate.claim), accepted),
        SOURCE_TIER[candidate.publisher_class],
        REPRESENTATIVENESS_RANK[labels.representativeness],
        0 if end is not None else 1,  # NULL last
        -end.toordinal() if end is not None else 0,  # newer first
        candidate.claim.claim_id,  # determinism
    )


def ranked(candidates: Iterable[Candidate], accepted: Sequence[GeographyLevel]) -> list[Candidate]:
    return sorted(candidates, key=lambda c: rank_key(c, accepted))


def select_for_verification(
    candidates: Iterable[Candidate], accepted: Sequence[GeographyLevel], params: VerifyParams
) -> list[Candidate]:
    """The top N matched claims of a slot in a round (§5.3). The rest stay `extracted`.

    The caller passes only matched, non-Wave-0 claims: Wave 0 claims are checked
    by code and never sent to the checker (HD-03).
    """
    return ranked(candidates, accepted)[: params.max_claims_per_slot]
