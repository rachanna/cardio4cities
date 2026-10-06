"""Extractor output (LLD-3 §4.3) and code validation (§4.4). The schema sent to the
provider carries no length limits; code enforces them here.

Two shapes (BD-45). `ExtractorWire` is what the provider fills: one flat object per
claim, every value a plain field, allowed values listed in field descriptions. The nested
`ExtractorOutput` with enums is what the rest of the code uses. Anthropic compiles a
strict schema into a grammar, and the nested one (five optional sub-objects and ten
enums inside a list) became too large to compile. `to_output` converts losslessly and
reports any value outside its vocabulary as a repair problem, so code enforces what the
grammar used to; `ExtractorWire.from_output` is the exact inverse."""

import re
from datetime import date
from enum import Enum

from pydantic import BaseModel, Field, field_validator

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
    Setting,
    Sex,
)

MAX_CLAIMS = 12
ENGLISH = frozenset({"en", "eng", "english"})
MAX_STATEMENT_CHARS = 300


class PeriodOut(BaseModel):
    start: str | None
    end: str | None


class PopulationOut(BaseModel):
    age_min: int | None
    age_max: int | None
    sex: Sex
    group: str | None
    # v3 (BD-22): true when the people measured are a part chosen by more than age, sex or
    # area (students, patients, workers, one community); a cascade denominator is not
    subgroup: bool | None = None


class LabelsOut(BaseModel):
    geography_level: GeographyLevel
    geography_name: str
    measure_type: MeasureType
    reference_period: PeriodOut | None
    population: PopulationOut
    setting: Setting | None
    sample_size_as_written: str | None  # v3: copied; code reads the number (BD-22)
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


class LabelQuotesOut(BaseModel):
    """Words copied from the source that state a label outside the quote (v2, BD-10)."""

    period: str | None
    geography: str | None
    population: str | None


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
    label_quotes: LabelQuotesOut | None

    @field_validator("quote_lang")
    @classmethod
    def _language_code(cls, value: str) -> str:
        """The primary language subtag: "en-GB", "EN", "eng" and "English" are all "en"
        (BD-22; code review RV-096). Other languages keep their code, lower-cased."""
        code = value.strip().lower().replace("_", "-").split("-")[0]
        return "en" if code in ENGLISH else code


class ExtractorOutput(BaseModel):
    claims: list[ClaimOut]


def repair_problems(output: ExtractorOutput) -> list[str]:
    """Problems that warrant one repair request (§4.4 'Repair')."""
    problems = []
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


def to_labels(
    out: LabelsOut, threshold_code: str | None, sample_size: int | None = None
) -> tuple[Labels, bool]:
    """Domain labels; the bool is True when a stated period did not parse (§4.4).
    `sample_size`: read by code from `sample_size_as_written` (BD-22)."""
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
        population_subgroup=out.population.subgroup,
        setting=out.setting,
        sample_size=sample_size,
        case_definition=out.case_definition,
        threshold_code=threshold_code,
        method=out.method,
        representativeness=out.representativeness,
        denominator_text=out.denominator_text,
        denominator_stated=out.denominator_stated,
    )
    return labels, unparsed


# --- The wire shape (BD-45) -------------------------------------------------------------


def _one_of(vocabulary: type[Enum], empty: bool = False) -> str:
    values = ", ".join(str(m.value) for m in vocabulary)
    return f"one of: {values}" + ("; empty when the source does not state it" if empty else "")


_TEXT = "empty when the source does not state it"
_STAT = "for kind statistic only; otherwise empty"
_REL = "for kind relation only; otherwise empty"
_DATE = "YYYY, YYYY-MM or YYYY-MM-DD"


class ClaimWire(BaseModel):
    """One claim as the provider returns it: flat, every field present."""

    slot_id: str
    kind: str = Field(description=_one_of(ClaimKind))
    statement: str
    quote: str
    quote_lang: str
    quote_translation: str = Field(
        description="English translation when quote_lang is not en; otherwise empty"
    )
    geography_level: str = Field(description=_one_of(GeographyLevel))
    geography_name: str
    measure_type: str = Field(
        description=f"{_one_of(MeasureType)}; qualitative for relation and statement claims"
    )
    period_start: str = Field(description=f"{_DATE}; {_TEXT}")
    period_end: str = Field(description=f"{_DATE}; {_TEXT}")
    age_min: int | None
    age_max: int | None
    sex: str = Field(description=_one_of(Sex))
    population_group: str = Field(description=_TEXT)
    subgroup: bool | None
    setting: str = Field(description=_one_of(Setting, empty=True))
    sample_size_as_written: str = Field(description=_TEXT)
    case_definition: str = Field(description=_TEXT)
    method: str = Field(description=_one_of(Method))
    representativeness: str = Field(description=_one_of(Representativeness))
    denominator_text: str = Field(description=_TEXT)
    denominator_stated: bool
    indicator_code: str = Field(description=f"from the list given, or OTHER; {_STAT}")
    value_as_written: str = Field(description=_STAT)
    subject_name: str = Field(description=_REL)
    subject_type: str = Field(description=f"{_one_of(EntityType)}; {_REL}")
    relation_type: str = Field(description=f"{_one_of(RelationType)}; {_REL}")
    object_name: str = Field(description=_REL)
    object_type: str = Field(description=f"{_one_of(EntityType)}; {_REL}")
    valid_from: str = Field(description=f"{_DATE}; {_REL}")
    valid_to: str = Field(description=f"{_DATE}; {_REL}")
    programme_status: str = Field(description=f"{_one_of(ProgrammeStatus)}; {_REL}")
    period_quote: str = Field(description=_TEXT)
    geography_quote: str = Field(description=_TEXT)
    population_quote: str = Field(description=_TEXT)


def _text(value: str | None) -> str:
    return value or ""


def _none(value: str) -> str | None:
    return value.strip() or None


class ExtractorWire(BaseModel):
    claims: list[ClaimWire]

    @classmethod
    def from_output(cls, out: "ExtractorOutput") -> "ExtractorWire":
        """The exact inverse of `to_output` (tests and recorded responses use it)."""
        return cls(claims=[_wire(c) for c in out.claims])


def _wire(c: "ClaimOut") -> ClaimWire:
    lab, st, rel, lq = c.labels, c.statistic, c.relation, c.label_quotes
    period = lab.reference_period
    return ClaimWire(
        slot_id=c.slot_id, kind=c.kind.value, statement=c.statement, quote=c.quote,
        quote_lang=c.quote_lang, quote_translation=_text(c.quote_translation),
        geography_level=lab.geography_level.value, geography_name=lab.geography_name,
        measure_type=lab.measure_type.value,
        period_start=_text(period.start if period else None),
        period_end=_text(period.end if period else None),
        age_min=lab.population.age_min, age_max=lab.population.age_max,
        sex=lab.population.sex.value, population_group=_text(lab.population.group),
        subgroup=lab.population.subgroup,
        setting=lab.setting.value if lab.setting else "",
        sample_size_as_written=_text(lab.sample_size_as_written),
        case_definition=_text(lab.case_definition), method=lab.method.value,
        representativeness=lab.representativeness.value,
        denominator_text=_text(lab.denominator_text), denominator_stated=lab.denominator_stated,
        indicator_code=st.indicator_code if st else "",
        value_as_written=st.value_as_written if st else "",
        subject_name=rel.subject_name if rel else "",
        subject_type=rel.subject_type.value if rel else "",
        relation_type=rel.relation_type.value if rel else "",
        object_name=rel.object_name if rel else "",
        object_type=rel.object_type.value if rel else "",
        valid_from=_text(rel.valid_from) if rel else "",
        valid_to=_text(rel.valid_to) if rel else "",
        programme_status=rel.programme_status.value if rel and rel.programme_status else "",
        period_quote=_text(lq.period) if lq else "",
        geography_quote=_text(lq.geography) if lq else "",
        population_quote=_text(lq.population) if lq else "",
    )  # fmt: skip


def _vocab[E: Enum](vocabulary: type[E], value: str, field: str, problems: list[str]) -> E | None:
    """A value of `vocabulary`, forgiving case, spaces and hyphens ("Measured prevalence",
    "measured-prevalence"); anything else is a problem for the repair request."""
    key = re.sub(r"[\s-]+", "_", value.strip()).casefold()
    for member in vocabulary:
        if str(member.value).casefold() == key:
            return member
    allowed = ", ".join(str(m.value) for m in vocabulary)
    problems.append(f"{field} {value!r} is not one of: {allowed}")
    return None


_NOT_APPLICABLE = frozenset({"", "not_applicable", "not applicable", "n/a", "none"})


def _or_not_stated[E: Enum](
    vocabulary: type[E], value: str, field: str, problems: list[str], not_stated: E
) -> E | None:
    """Blank means the source does not state it: the vocabulary's own `not_stated`."""
    return not_stated if not value.strip() else _vocab(vocabulary, value, field, problems)


def _relation(w: ClaimWire, problems: list[str]) -> RelationOut | None:
    fields = (w.subject_name, w.subject_type, w.relation_type, w.object_name, w.object_type,
              w.valid_from, w.valid_to, w.programme_status)  # fmt: skip
    if not any(f.strip() for f in fields):
        return None
    s_type = _vocab(EntityType, w.subject_type, "subject_type", problems)
    r_type = _vocab(RelationType, w.relation_type, "relation_type", problems)
    o_type = _vocab(EntityType, w.object_type, "object_type", problems)
    status = None
    if w.programme_status.strip():
        status = _vocab(ProgrammeStatus, w.programme_status, "programme_status", problems)
    if s_type is None or r_type is None or o_type is None:
        return None
    return RelationOut(
        subject_name=w.subject_name, subject_type=s_type, relation_type=r_type,
        object_name=w.object_name, object_type=o_type, valid_from=_none(w.valid_from),
        valid_to=_none(w.valid_to), programme_status=status,
    )  # fmt: skip


def _claim(n: int, w: ClaimWire, problems: list[str]) -> "ClaimOut | None":
    mine: list[str] = []
    kind = _vocab(ClaimKind, w.kind, "kind", mine)
    level = _vocab(GeographyLevel, w.geography_level, "geography_level", mine)
    if kind is not ClaimKind.STATISTIC and w.measure_type.strip().casefold() in _NOT_APPLICABLE:
        measure: MeasureType | None = MeasureType.QUALITATIVE  # what a non-figure measures
    else:
        measure = _vocab(MeasureType, w.measure_type, "measure_type", mine)
    sex = _or_not_stated(Sex, w.sex, "sex", mine, Sex.NOT_STATED)
    setting = _vocab(Setting, w.setting, "setting", mine) if w.setting.strip() else None
    method = _or_not_stated(Method, w.method, "method", mine, Method.NOT_STATED)
    rep = _or_not_stated(
        Representativeness, w.representativeness, "representativeness", mine,
        Representativeness.NOT_STATED,
    )  # fmt: skip
    relation = _relation(w, mine)
    problems += [f"claim {n}: {p}" for p in mine]
    if mine or kind is None or level is None or measure is None or sex is None:
        return None
    if method is None or rep is None:
        return None
    statistic = None
    if w.indicator_code.strip() or w.value_as_written.strip():
        statistic = StatisticOut(
            indicator_code=w.indicator_code.strip(), value_as_written=w.value_as_written
        )
    period = None
    if w.period_start.strip() or w.period_end.strip():
        period = PeriodOut(start=_none(w.period_start), end=_none(w.period_end))
    quotes = None
    if any(q.strip() for q in (w.period_quote, w.geography_quote, w.population_quote)):
        quotes = LabelQuotesOut(
            period=_none(w.period_quote), geography=_none(w.geography_quote),
            population=_none(w.population_quote),
        )  # fmt: skip
    return ClaimOut(
        slot_id=w.slot_id, kind=kind, statement=w.statement, quote=w.quote,
        quote_lang=w.quote_lang, quote_translation=_none(w.quote_translation),
        labels=LabelsOut(
            geography_level=level, geography_name=w.geography_name, measure_type=measure,
            reference_period=period,
            population=PopulationOut(
                age_min=w.age_min, age_max=w.age_max, sex=sex,
                group=_none(w.population_group), subgroup=w.subgroup,
            ),
            setting=setting, sample_size_as_written=_none(w.sample_size_as_written),
            case_definition=_none(w.case_definition), method=method, representativeness=rep,
            denominator_text=_none(w.denominator_text), denominator_stated=w.denominator_stated,
        ),
        statistic=statistic, relation=relation, label_quotes=quotes,
    )  # fmt: skip


def to_output(wire: ExtractorWire) -> tuple["ExtractorOutput", list[str]]:
    """The nested output, and the problems that warrant a repair request: a value outside
    its vocabulary (that claim is left out), then the checks of `repair_problems`."""
    problems: list[str] = []
    claims = [c for n, w in enumerate(wire.claims, 1) if (c := _claim(n, w, problems))]
    out = ExtractorOutput(claims=claims)
    return out, problems + repair_problems(out)


def wire_problems(wire: ExtractorWire) -> list[str]:
    return to_output(wire)[1]
