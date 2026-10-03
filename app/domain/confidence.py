"""Confidence label (LLD-2 §7, R-48): deterministic, computed at read time for
supported or contested claims, returned with its reasons."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.dates import years_before
from app.domain.geography import effective_level
from app.domain.models import Claim, Verdict
from app.domain.params import ConfidenceParams
from app.domain.vocab import (
    DENOMINATOR_MEASURES,
    SHOWABLE_STATUSES,
    ClaimFlag,
    ConfidenceLabel,
    GeographyLevel,
    PeriodType,
    PublisherClass,
    Representativeness,
)

TIER_POINTS: dict[PublisherClass, int] = {
    PublisherClass.GOVERNMENT: 2,
    PublisherClass.MULTILATERAL: 2,
    PublisherClass.ACADEMIC: 2,
    PublisherClass.NGO: 1,
    PublisherClass.NEWS: 0,
    PublisherClass.OTHER: 0,
}
REPRESENTATIVENESS_POINTS: dict[Representativeness, int] = {
    Representativeness.CENSUS: 2,
    Representativeness.REPRESENTATIVE_SAMPLE: 2,
    Representativeness.MODELLED: 1,
    Representativeness.NOT_APPLICABLE: 1,
    Representativeness.NON_REPRESENTATIVE: 0,
}
HIGH_FROM, MEDIUM_FROM = 7, 4  # out of 9: High >= 7, Medium 4-6, Low <= 3


@dataclass(frozen=True)
class Reason:
    component: str
    points: int
    note: str


@dataclass(frozen=True)
class Confidence:
    label: ConfidenceLabel
    points: int
    reasons: tuple[Reason, ...]
    capped_by: str | None = None  # why the label was held at Medium


def confidence(
    claim: Claim,
    publisher_class: PublisherClass,
    accepted: Sequence[GeographyLevel],
    verdict: Verdict | None,
    today: date,
    params: ConfidenceParams,
) -> Confidence:
    if claim.status not in SHOWABLE_STATUSES:
        raise ValueError(f"confidence applies to supported or contested claims, not {claim.status}")
    labels = claim.labels
    in_area = effective_level(claim) in accepted
    recent = labels.reference_end is not None and labels.reference_end >= years_before(
        today, params.recent_years
    )
    denominator_ok = labels.denominator_stated or labels.measure_type not in DENOMINATOR_MEASURES
    verified = verdict is not None and verdict.scope_verified and verdict.period_verified
    reasons = (
        Reason("source_tier", TIER_POINTS[publisher_class], f"{publisher_class.value} source"),
        Reason(
            "representativeness",
            REPRESENTATIVENESS_POINTS[labels.representativeness],
            labels.representativeness.value.replace("_", " "),
        ),
        Reason(
            "geography_fit",
            2 if in_area else 0,
            "Matches the question's area" if in_area else "Wider area than the question",
        ),
        Reason(
            "recency",
            1 if recent else 0,
            f"Within {params.recent_years} years" if recent else "Older or undated",
        ),
        Reason(
            "denominator",
            1 if denominator_ok else 0,
            "Denominator stated or not needed" if denominator_ok else "Denominator not stated",
        ),
        Reason(
            "verdict_scope_period",
            1 if verified else 0,
            "Area and period confirmed by the checker"
            if verified
            else "Area or period unconfirmed",
        ),
    )
    points = sum(r.points for r in reasons)
    label = (
        ConfidenceLabel.HIGH
        if points >= HIGH_FROM
        else ConfidenceLabel.MEDIUM
        if points >= MEDIUM_FROM
        else ConfidenceLabel.LOW
    )
    cap = None
    if verdict is not None and verdict.fallback_used:
        cap = "same-family fallback checker"
    elif (
        ClaimFlag.PERIOD_NOT_STATED in claim.flags
        or labels.period_type is PeriodType.PUBLICATION_DATE_PROXY
    ):
        cap = "reference period not stated"
    if cap is not None and label is ConfidenceLabel.HIGH:
        return Confidence(ConfidenceLabel.MEDIUM, points, reasons, capped_by=cap)
    return Confidence(label, points, reasons)
