"""Extractor output (LLD-3 §4.3) and code validation (§4.4). The schema sent to the
provider carries no length limits; code enforces them here."""

import re
from datetime import date

from pydantic import BaseModel

from app.domain.models import Labels
from app.domain.vocab import (
    RELATION_PAIRS,
    ClaimKind,
    DatePrecision,
    EntityType,
    GeographyLevel,
    MeasureType,
    Method,
    PeriodType,
    ProgrammeStatus,
    RelationType,
    Representativeness,
    Sex,
)

MAX_CLAIMS = 12
MAX_STATEMENT_CHARS = 300


class PeriodOut(BaseModel):
    start: str | None
    end: str | None


class PopulationOut(BaseModel):
    age_min: int | None
    age_max: int | None
    sex: Sex
    group: str | None


class LabelsOut(BaseModel):
    geography_level: GeographyLevel
    geography_name: str
    measure_type: MeasureType
    reference_period: PeriodOut | None
    population: PopulationOut
    setting: str | None
    sample_size: int | None
    case_definition: str | None
    method: Method
    representativeness: Representativeness
    denominator_text: str | None
    denominator_stated: bool


class StatisticOut(BaseModel):
    indicator_code: str  # from the provided list, or 'OTHER'
    value_as_written: str


class RelationOut(BaseModel):
    subject_name: str
    subject_type: EntityType
    relation_type: RelationType
    object_name: str
    object_type: EntityType
    valid_from: str | None
    valid_to: str | None
    programme_status: ProgrammeStatus | None


class ClaimOut(BaseModel):
    slot_id: str
    kind: ClaimKind
    statement: str
    quote: str
    quote_lang: str
    quote_translation: str | None
    labels: LabelsOut
    statistic: StatisticOut | None
    relation: RelationOut | None


class ExtractorOutput(BaseModel):
    claims: list[ClaimOut]


def repair_problems(output: ExtractorOutput) -> list[str]:
    """Problems that warrant one repair request (§4.4 'Repair')."""
    problems = []
    if len(output.claims) > MAX_CLAIMS:
        problems.append(f"return at most {MAX_CLAIMS} claims")
    for n, c in enumerate(output.claims, 1):
        if (c.kind is ClaimKind.STATISTIC) != (c.statistic is not None):
            problems.append(f"claim {n}: kind statistic needs a statistic block, and only then")
        if (c.kind is ClaimKind.RELATION) != (c.relation is not None):
            problems.append(f"claim {n}: kind relation needs a relation block, and only then")
        if c.quote_lang != "en" and not c.quote_translation:
            problems.append(f"claim {n}: add quote_translation for a non-English quote")
    return problems


def keep_claim(claim: ClaimOut, slot_ids: set[str]) -> bool:
    """Claims dropped silently by validation (§4.4 'Drop that claim')."""
    if claim.slot_id not in slot_ids:
        return False
    if claim.relation is not None:
        pair = (claim.relation.subject_type, claim.relation.object_type)
        if pair not in RELATION_PAIRS[claim.relation.relation_type]:
            return False
    return bool(claim.quote.strip()) and len(claim.statement) <= MAX_STATEMENT_CHARS


_PARTIAL = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")


def parse_partial_date(value: str | None, end: bool) -> tuple[date | None, DatePrecision | None]:
    """'2024' / '2024-03' / '2024-03-15' -> a date (first or last day) and its precision."""
    if not value:
        return None, None
    m = _PARTIAL.match(value.strip())
    if not m:
        return None, None
    year, month, day = int(m[1]), m[2], m[3]
    try:
        if day:
            return date(year, int(month), int(day)), DatePrecision.DAY
        if month:
            mo = int(month)
            if end:
                nxt = date(year + (mo == 12), mo % 12 + 1, 1)
                return date.fromordinal(nxt.toordinal() - 1), DatePrecision.MONTH
            return date(year, mo, 1), DatePrecision.MONTH
        return (date(year, 12, 31) if end else date(year, 1, 1)), DatePrecision.YEAR
    except ValueError:
        return None, None


def to_labels(out: LabelsOut, threshold_code: str | None) -> tuple[Labels, bool]:
    """Domain labels; the bool is True when a stated period did not parse (§4.4)."""
    period = out.reference_period
    start, p_start = parse_partial_date(period.start if period else None, end=False)
    end_, p_end = parse_partial_date(period.end if period else None, end=True)
    if start and not end_ and period and period.start:
        end_, p_end = parse_partial_date(period.start, end=True)  # a single year or month
    unparsed = bool(period and (period.start or period.end) and not (start or end_))
    if start and end_ and start > end_:
        start, end_, unparsed = None, None, True
    labels = Labels(
        geography_level=out.geography_level,
        geography_name=out.geography_name,
        measure_type=out.measure_type,
        reference_start=start,
        reference_end=end_,
        reference_precision=p_end or p_start,
        period_type=PeriodType.PERIOD if (start or end_) else PeriodType.PUBLICATION_DATE_PROXY,
        population_age_min=out.population.age_min,
        population_age_max=out.population.age_max,
        population_sex=out.population.sex,
        population_group=out.population.group,
        setting=out.setting,
        sample_size=out.sample_size,
        case_definition=out.case_definition,
        threshold_code=threshold_code,
        method=out.method,
        representativeness=out.representativeness,
        denominator_text=out.denominator_text,
        denominator_stated=out.denominator_stated,
    )
    return labels, unparsed
