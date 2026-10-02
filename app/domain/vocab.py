"""Controlled vocabularies (LLD-1 §1). Database CHECK constraints use the same values."""

from enum import StrEnum

# --- 1.1 Claims and statistics -------------------------------------------------


class ClaimKind(StrEnum):
    STATISTIC = "statistic"
    RELATION = "relation"
    STATEMENT = "statement"


class GeographyLevel(StrEnum):
    """What a figure actually describes, ordered from finest to broadest."""

    CITY_WIDE = "city_wide"
    SUB_CITY_AREA = "sub_city_area"
    SUB_CITY_POPULATION = "sub_city_population"
    METRO_REGION = "metro_region"
    DISTRICT = "district"
    STATE_PROVINCE = "state_province"
    NATIONAL = "national"
    GLOBAL = "global"


GEOGRAPHY_ORDER: tuple[GeographyLevel, ...] = tuple(GeographyLevel)


class Representativeness(StrEnum):
    REPRESENTATIVE_SAMPLE = "representative_sample"
    CENSUS = "census"
    NON_REPRESENTATIVE = "non_representative"
    MODELLED = "modelled"
    NOT_APPLICABLE = "not_applicable"


class MeasureType(StrEnum):
    MEASURED_PREVALENCE = "measured_prevalence"
    SELF_REPORTED_PREVALENCE = "self_reported_prevalence"
    SCREENING_POSITIVITY = "screening_positivity"  # never prevalence (T-04)
    CASCADE_AWARENESS = "cascade_awareness"
    CASCADE_TREATMENT = "cascade_treatment"
    CASCADE_CONTROL = "cascade_control"
    SHARE_OF_SUBGROUP = "share_of_subgroup"
    INCIDENCE = "incidence"
    MORTALITY_RATE = "mortality_rate"
    PROGRAMME_OUTPUT = "programme_output"  # never prevalence (T-04)
    MODELLED_ESTIMATE = "modelled_estimate"
    TARGET = "target"
    BUDGET = "budget"
    POPULATION_COUNT = "population_count"
    QUALITATIVE = "qualitative"


# Measures whose meaning depends on a stated denominator (LLD-2 §7, AT-21)
DENOMINATOR_MEASURES: frozenset[MeasureType] = frozenset(
    {
        MeasureType.MEASURED_PREVALENCE,
        MeasureType.SELF_REPORTED_PREVALENCE,
        MeasureType.CASCADE_AWARENESS,
        MeasureType.CASCADE_TREATMENT,
        MeasureType.CASCADE_CONTROL,
    }
)


class Method(StrEnum):
    MEASURED = "measured"
    SELF_REPORTED = "self_reported"
    MODELLED = "modelled"
    ADMINISTRATIVE = "administrative"
    NOT_STATED = "not_stated"


class PeriodType(StrEnum):
    POINT_IN_TIME = "point_in_time"
    PERIOD = "period"
    CUMULATIVE = "cumulative"
    PUBLICATION_DATE_PROXY = "publication_date_proxy"  # always flagged period_not_stated


class DatePrecision(StrEnum):
    DAY = "day"
    MONTH = "month"
    YEAR = "year"


class Sex(StrEnum):
    ALL = "all"
    FEMALE = "female"
    MALE = "male"
    NOT_STATED = "not_stated"


class ClaimStatus(StrEnum):
    EXTRACTED = "extracted"
    DROPPED = "dropped"
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INSUFFICIENT = "insufficient"
    CONTESTED = "contested"
    SUPERSEDED = "superseded"


SHOWABLE_STATUSES: frozenset[ClaimStatus] = frozenset(
    {ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED}
)


class ClaimFlag(StrEnum):
    PERIOD_NOT_STATED = "period_not_stated"
    DENOMINATOR_NOT_STATED = "denominator_not_stated"
    SMALL_SAMPLE = "small_sample"
    NON_REPRESENTATIVE = "non_representative"
    REPUBLISHED = "republished"
    TRANSLATED = "translated"
    VALUE_UNPARSED = "value_unparsed"
    SETTING_NOT_STATED = "setting_not_stated"
    GOVERNING_BODY_UNCERTAIN = "governing_body_uncertain"


# --- 1.2 Sources, crawling, verification -----------------------------------------


class SourceKind(StrEnum):
    WEB_HTML = "web_html"
    WEB_PDF = "web_pdf"
    STRUCTURED_API = "structured_api"


class PublisherClass(StrEnum):
    """Declaration order is also the source tier, best first."""

    GOVERNMENT = "government"
    MULTILATERAL = "multilateral"
    ACADEMIC = "academic"
    NGO = "ngo"
    NEWS = "news"
    OTHER = "other"


class CrawlOutcome(StrEnum):
    ALLOWED = "allowed"
    BLOCKED_ROBOTS = "blocked_robots"
    BLOCKED_CONTENT_USAGE = "blocked_content_usage"
    BLOCKED_LOGIN_OR_PAYWALL = "blocked_login_or_paywall"
    BLOCKED_PRIVATE_ADDRESS = "blocked_private_address"
    UNREACHABLE_NETWORK = "unreachable_network"
    UNREACHABLE_SERVER_ERROR = "unreachable_server_error"
    RATE_LIMITED = "rate_limited"


class ParseOutcome(StrEnum):
    PARSED = "parsed"
    UNREADABLE = "unreadable"
    TOO_LARGE = "too_large"
    UNSUPPORTED_TYPE = "unsupported_type"


class VerdictLabel(StrEnum):
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INSUFFICIENT = "insufficient"


class ConsistencyOutcome(StrEnum):
    AGREES = "agrees"
    NOVEL = "novel"
    CONFLICTS = "conflicts"
    NOT_COMPARABLE = "not_comparable"


# --- 1.3 Runs, slots, events ------------------------------------------------------


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED_BY_BUDGET = "stopped_by_budget"
    FAILED = "failed"


class SlotStatus(StrEnum):
    ANSWERED = "answered"
    ANSWERED_WIDER_GEO = "answered_wider_geo"
    ANSWERED_NEGATIVE = "answered_negative"
    BLOCKED = "blocked"
    UNREACHABLE = "unreachable"


class SlotFlag(StrEnum):
    CONFLICTING = "conflicting"
    STALE = "stale"


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    IDENTITY_CONFIRMED = "identity_confirmed"
    WAVE0_FINDING = "wave0_finding"
    SLOT_PLANNED = "slot_planned"
    SEARCH_DONE = "search_done"
    CRAWL_DECISION = "crawl_decision"
    SOURCE_FETCHED = "source_fetched"
    SOURCE_UNREADABLE = "source_unreadable"
    CLAIM_EXTRACTED = "claim_extracted"
    CLAIM_DROPPED = "claim_dropped"
    CLAIM_VERDICT = "claim_verdict"
    CONFLICT_FOUND = "conflict_found"
    FACT_WRITTEN = "fact_written"
    SLOT_STATUS = "slot_status"
    BUDGET_WARNING = "budget_warning"
    RUN_FINISHED = "run_finished"


# --- 1.4 Presentation (computed, never stored) -------------------------------------


class Badge(StrEnum):
    """Declaration order is severity, most severe first (R-78)."""

    NOT_CITY_LEVEL = "not_city_level"
    SOURCES_DISAGREE = "sources_disagree"
    OUTDATED = "outdated"
    LIMITED_SAMPLE = "limited_sample"


class ConfidenceLabel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class StatementKind(StrEnum):
    CONFIRMED = "confirmed"
    REPORTED_NOT_CONFIRMED = "reported_not_confirmed"
    ANALYSIS = "analysis"
    NOT_FOUND = "not_found"


# --- Graph (LLD-1 §6) ------------------------------------------------------------


class AnswerKind(StrEnum):
    STATISTIC = "statistic"
    RELATION = "relation"
    STATEMENT = "statement"
    MIXED = "mixed"


class RelationType(StrEnum):
    """Graph relation types (LLD-1 §6.2)."""

    GOVERNS = "GOVERNS"
    REPLACED_BY = "REPLACED_BY"
    PART_OF = "PART_OF"
    RUNS = "RUNS"
    FUNDS = "FUNDS"
    PARTNERS_WITH = "PARTNERS_WITH"
    OPERATES_IN = "OPERATES_IN"
    ISSUED_BY = "ISSUED_BY"
    APPLIES_TO = "APPLIES_TO"
    LEADS = "LEADS"
    MEASURED_IN = "MEASURED_IN"


# One current edge allowed per object (place or organisation); LLD-1 §6.2, LLD-2 §5.5
SINGLE_CURRENT_RELATIONS: frozenset[RelationType] = frozenset(
    {RelationType.GOVERNS, RelationType.LEADS}
)
