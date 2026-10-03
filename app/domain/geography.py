"""The level a claim counts as for the researched city (BD-10). A figure about a nearby
place is never city-level, whatever level it has for its own place: a neighbouring
town's city-wide figure counts as at least district-wide, so ranking, badges, confidence
and slot status all treat it as wider-area evidence."""

from app.domain.models import Claim
from app.domain.vocab import GEOGRAPHY_ORDER, GeographyLevel, GeographyRelation

NEARBY_LEVEL = GeographyLevel.DISTRICT


def effective_level(claim: Claim) -> GeographyLevel:
    level = claim.labels.geography_level
    fit = claim.geography_fit
    if fit is None or fit.relation is not GeographyRelation.NEARBY:
        return level
    return max(level, NEARBY_LEVEL, key=GEOGRAPHY_ORDER.index)
