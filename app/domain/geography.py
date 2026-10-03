"""The level a claim counts as for the researched city (BD-10, BD-17). A figure about a
nearby place is never city-level, whatever level it has for its own place: a neighbouring
town's city-wide figure counts as at least district-wide. A figure about an area that
contains the city ("Greater X", "X Metropolitan Region") counts as at least metro-region
even when it was labelled city-wide. Ranking, badges, confidence and slot status all
treat both as wider-area evidence."""

from app.domain.models import Claim
from app.domain.vocab import GEOGRAPHY_ORDER, GeographyLevel, GeographyRelation

NEARBY_LEVEL = GeographyLevel.DISTRICT
CONTAINING_LEVEL = GeographyLevel.METRO_REGION


def effective_level(claim: Claim) -> GeographyLevel:
    level = claim.labels.geography_level
    fit = claim.geography_fit
    if fit is None:
        return level
    if fit.relation is GeographyRelation.NEARBY:
        return max(level, NEARBY_LEVEL, key=GEOGRAPHY_ORDER.index)
    if fit.relation is GeographyRelation.CONTAINS_CITY:
        return max(level, CONTAINING_LEVEL, key=GEOGRAPHY_ORDER.index)
    return level
