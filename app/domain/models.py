"""Domain types (LLD-1 §2). Pydantic v2; field names, types and validators are binding."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.vocab import (
    AnswerKind,
    ClaimFlag,
    ClaimKind,
    ClaimStatus,
    ConsistencyOutcome,
    CrawlOutcome,
    DatePrecision,
    EntityType,
    GeographyLevel,
    GeographyRelation,
    MeasureType,
    Method,
    ParseOutcome,
    PeriodType,
    PublisherClass,
    RelationType,
    Representativeness,
    Sex,
    SlotFlag,
    SlotStatus,
    SourceKind,
    VerdictLabel,
)

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class SlotDef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    slot_id: str = Field(pattern=r"^S(0[1-9]|1[0-6])$")  # 'S01'…'S16'
    dimension: str = Field(pattern=r"^D[1-6]$")  # 'D1'…'D6'
    question: str  # plain-language question shown in UI
    short_label: str  # used in abstentions: "No confirmed {short_label} for {city}" (BD-03)
    answer_kind: AnswerKind
    indicator_codes: list[str]  # for statistic slots; LLD-1 §3.3
    relation_types: list[RelationType]  # for relation slots; LLD-1 §6.2
    headline: bool  # True only for S04
    accepted_levels: list[GeographyLevel]  # levels that count as 'answered'

    @model_validator(mode="after")
    def _kind_matches_targets(self) -> "SlotDef":
        has_indicators, has_relations = bool(self.indicator_codes), bool(self.relation_types)
        expected = {
            AnswerKind.STATISTIC: (True, False),
            AnswerKind.RELATION: (False, True),
            AnswerKind.STATEMENT: (False, False),
            AnswerKind.MIXED: (False, True),
        }[self.answer_kind]
        if (has_indicators, has_relations) != expected:
            raise ValueError(
                f"{self.slot_id}: answer_kind {self.answer_kind} does not fit "
                f"indicator_codes={self.indicator_codes} relation_types={self.relation_types}"
            )
        if not self.accepted_levels:
            raise ValueError(f"{self.slot_id}: accepted_levels must not be empty")
        return self


class IndicatorDef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str = Field(pattern=r"^[A-Z][A-Z0-9_]*$")
    name: str
    comparability_key: str  # which labels make two claims comparable (R-35)
    notes: str | None = None


# --- 2.1 City identity ----------------------------------------------------------


class CityIdentity(BaseModel):
    model_config = _FROZEN

    city_id: str  # city_…
    gazetteer_id: str
    name: str
    ascii_name: str
    country_iso2: str = Field(min_length=2, max_length=2)
    country_iso3: str = Field(min_length=3, max_length=3)
    country_name: str
    admin1_code: str | None
    admin1_name: str | None
    admin2_name: str | None
    population: int | None  # from the gazetteer; sanity checks only (T-10)
    lat: float
    lon: float
    languages: list[str]  # ISO 639-1; first is primary


# --- 2.3 Claim and labels -------------------------------------------------------


class Labels(BaseModel):
    """Required labels first (R-89); optional ones are None when the source does not state them."""

    model_config = _FROZEN

    geography_level: GeographyLevel
    geography_name: str
    measure_type: MeasureType
    reference_start: date | None
    reference_end: date | None
    reference_precision: DatePrecision | None
    period_type: PeriodType
    population_age_min: int | None = None
    population_age_max: int | None = None
    population_sex: Sex = Sex.NOT_STATED
    population_group: str | None = None
    setting: str | None = None
    sample_size: int | None = None
    case_definition: str | None = None
    threshold_code: str | None = None  # set by code (LLD-2 §4.3)
    method: Method = Method.NOT_STATED
    representativeness: Representativeness
    denominator_text: str | None = None
    denominator_stated: bool

    @model_validator(mode="after")
    def _ordered(self) -> "Labels":
        if (
            self.reference_start
            and self.reference_end
            and self.reference_start > self.reference_end
        ):
            raise ValueError("reference_start is after reference_end")
        low, high = self.population_age_min, self.population_age_max
        if low is not None and high is not None and low > high:
            raise ValueError("population_age_min is above population_age_max")
        return self


class GeographyFit(BaseModel):
    """Set by code from the gazetteer (BD-10); shown in the evidence panel."""

    model_config = _FROZEN

    relation: GeographyRelation
    place_name: str | None = None  # the gazetteer place or area the name resolved to
    distance_km: int | None = None  # from the city, for places resolved to a point


LabelKind = Literal["period", "population", "geography"]


class Entity(BaseModel):
    """One real-world entity per city across sources and runs (LLD-1 §4.4, LLD-2 §6, R-43)."""

    model_config = _FROZEN

    entity_id: str  # ent_…
    city_id: str
    entity_type: EntityType
    canonical_name: str
    normalized_key: str
    graph_uuid: str  # uuid5(NAMESPACE, entity_id)
    attributes: dict[str, Any] = Field(default_factory=dict)


class Claim(BaseModel):
    model_config = _FROZEN

    claim_id: str  # clm_…
    run_id: str
    city_id: str
    slot_id: str
    source_id: str
    kind: ClaimKind
    statement: str
    quote: str  # verbatim, original language
    quote_lang: str
    quote_translation: str | None
    span_start: int = Field(ge=0)
    span_end: int
    labels: Labels
    flags: frozenset[ClaimFlag] = frozenset()
    status: ClaimStatus
    extractor_model: str
    prompt_version: str
    # Where a label is stated outside the quote, located by code (BD-10)
    label_spans: dict[LabelKind, tuple[int, int]] = Field(default_factory=dict)
    geography_fit: GeographyFit | None = None

    @model_validator(mode="after")
    def _span(self) -> "Claim":
        if self.span_end <= self.span_start:
            raise ValueError("span_end must be after span_start")
        return self


# --- 2.4 Statistic --------------------------------------------------------------


class Statistic(BaseModel):
    model_config = _FROZEN

    claim_id: str
    indicator_code: str  # 'OTHER' allowed, never compared
    value_as_written: str
    value_num: Decimal | None  # parsed by code (LLD-2 §4.2), never by a model
    unit: str | None
    lower: Decimal | None = None
    upper: Decimal | None = None


# --- 2.5 Relation ---------------------------------------------------------------


class Relation(BaseModel):
    model_config = _FROZEN

    claim_id: str
    subject_entity_id: str
    relation_type: RelationType
    object_entity_id: str
    valid_from: date | None
    valid_to: date | None
    valid_from_is_proxy: bool = False


# --- 2.6 Verdict, consistency, source, crawl decision ---------------------------


class Verdict(BaseModel):
    model_config = _FROZEN

    claim_id: str
    label: VerdictLabel
    rationale: str = Field(max_length=400)
    scope_verified: bool
    period_verified: bool
    verifier_model: str
    verifier_family: str
    fallback_used: bool = False
    prompt_version: str


class ConsistencyResult(BaseModel):
    model_config = _FROZEN

    claim_id: str
    outcome: ConsistencyOutcome
    compared_with: list[str]
    reason: str  # template text from code


class Source(BaseModel):
    model_config = _FROZEN

    source_id: str  # src_…
    run_id: str
    url: str
    url_canonical: str
    domain: str
    kind: SourceKind
    publisher_class: PublisherClass
    title: str | None
    language: str | None
    published_date: date | None
    published_precision: DatePrecision | None
    retrieved_at: datetime
    http_status: int | None
    content_type: str | None
    content_sha256: str | None
    size_bytes: int | None
    parse_outcome: ParseOutcome | None
    found_via: str


class CrawlDecision(BaseModel):
    model_config = _FROZEN

    decision_id: str  # cd_…
    run_id: str
    url: str
    domain: str
    outcome: CrawlOutcome
    rule: str | None
    reason: str
    robots_http_status: int | None
    decided_at: datetime


# --- 2.7 Slot result and run summary ---------------------------------------------


class SlotResult(BaseModel):
    model_config = _FROZEN

    run_id: str
    slot_id: str
    status: SlotStatus
    flags: frozenset[SlotFlag] = frozenset()
    replans_used: int = 0
    queries_tried: list[str] = []
    sources_checked: list[str] = []
    best_claim_ids: list[str] = []
    gap_note: str | None = None


class RunSummary(BaseModel):
    model_config = _FROZEN

    run_id: str
    claims_extracted: int = 0
    claims_dropped_quote: int = 0
    claims_supported: int = 0
    claims_refuted: int = 0
    claims_insufficient: int = 0
    claims_contested: int = 0
    sources_fetched: int = 0
    sources_blocked: int = 0
    sources_unreachable: int = 0
    sources_unreadable: int = 0
    searches_used: int = 0
    fetches_used: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_micro_usd: int = 0
    wall_clock_ms: int = 0
    by_model: dict[str, dict[str, Any]] = {}
