"""Checker input: the restricted slice (LLD-3 §5.1, R-38, AT-07). Binding: the checker
receives the claim, its labels, its value and the code-located passages (around the
quote, and around any label quote, BD-10), and nothing else: never the extractor's
prompt or output, other claims, other sources, or the slot question.
`build_user_message` takes exactly these inputs, so nothing else can reach it."""

from collections.abc import Sequence
from datetime import date

from app.domain.models import Labels
from app.domain.vocab import DatePrecision, GeographyLevel, MeasureType
from app.prompts.safety import escape_untrusted as _e
from app.prompts.safety import wrap_source

PASSAGE_MARGIN_CHARS = 600  # LLD-3 §5.1: the quote plus up to 600 characters either side


def passage(
    parsed_text: str, span_start: int, span_end: int, margin: int = PASSAGE_MARGIN_CHARS
) -> str:
    start = max(0, span_start - margin)
    end = min(len(parsed_text), span_end + margin)
    return parsed_text[start:end]


def _at(day: date, precision: DatePrecision | None) -> str:
    if precision is DatePrecision.YEAR:
        return str(day.year)
    if precision is DatePrecision.MONTH:
        return day.strftime("%Y-%m")
    return day.isoformat()


def _period(labels: Labels) -> str:
    """At the precision the source stated: a year stays "2024", never "2024-01-01 to
    2024-12-31", which no passage states (golden set, BD-10)."""
    start, end = labels.reference_start, labels.reference_end
    if labels.period_type.value == "publication_date_proxy" or not (start or end):
        return "not stated"
    precision = labels.reference_precision
    first = _at(start, precision) if start else None
    last = _at(end, precision) if end else None
    if first and last and first != last:
        return f"{first} to {last}"
    return first or last or "not stated"


def ages(low: int | None, high: int | None) -> str:
    if low is not None and high is not None:
        return f"aged {low}-{high}"
    if low is not None:
        return f"aged {low} and over"
    if high is not None:
        return f"aged up to {high}"
    return "age not stated"


def population(labels: Labels) -> str:
    """Unstated parts read "not stated", never a default that asserts something."""
    sex = labels.population_sex.value.replace("_", " ")
    return (
        f"{ages(labels.population_age_min, labels.population_age_max)}; sex {sex}; "
        f"group {labels.population_group or 'not stated'}; "
        f"setting {labels.setting or 'not stated'}"
    )


# Plain words for the level (golden set: the bare code "city_wide" read as a mismatch for
# a place the passage calls a town)
LEVEL_WORDS = {
    GeographyLevel.CITY_WIDE: "the whole city or town",
    GeographyLevel.SUB_CITY_AREA: "part of a city",
    GeographyLevel.SUB_CITY_POPULATION: "a population group within a city",
    GeographyLevel.METRO_REGION: "a metropolitan region",
    GeographyLevel.DISTRICT: "a district",
    GeographyLevel.STATE_PROVINCE: "a state or province",
    GeographyLevel.NATIONAL: "a whole country",
    GeographyLevel.GLOBAL: "the world",
}

# Plain words, not codes (code review RV-096): "cascade_control" read as jargon
MEASURE_WORDS = {
    MeasureType.MEASURED_PREVALENCE: "prevalence, measured",
    MeasureType.SELF_REPORTED_PREVALENCE: "prevalence, self-reported",
    MeasureType.PREVALENCE: "prevalence, method not stated",
    MeasureType.SCREENING_POSITIVITY: "share of people screened who tested positive",
    MeasureType.CASCADE_AWARENESS: "share of people with the condition who know they have it",
    MeasureType.CASCADE_TREATMENT: "share of people with the condition who are treated",
    MeasureType.CASCADE_CONTROL: "share of people with the condition who have it controlled",
    MeasureType.SHARE_OF_SUBGROUP: "share of a subgroup",
    MeasureType.INCIDENCE: "incidence (new cases)",
    MeasureType.MORTALITY_RATE: "death rate",
    MeasureType.PROGRAMME_OUTPUT: "programme output (a count of services or people reached)",
    MeasureType.MODELLED_ESTIMATE: "modelled estimate",
    MeasureType.TARGET: "target",
    MeasureType.BUDGET: "budget",
    MeasureType.POPULATION_COUNT: "population count",
    MeasureType.QUALITATIVE: "a statement, not a figure",
}

LABEL_PASSAGE_TITLES = {
    "period": "passage stating the period",
    "geography": "passage stating the area",
    "population": "passage stating the population",
}


def build_user_message(
    statement: str,
    value_as_written: str | None,
    labels: Labels,
    source_id: str,
    publisher_class: str,
    published: date | None,
    passage_text: str,
    label_passages: Sequence[tuple[str, str]] = (),
) -> str:
    """`label_passages`: (label kind, text) for labels stated outside the quote, each
    located by code (BD-10)."""
    lines = [
        "<task>Decide whether the passages support the claim exactly as labelled.</task>",
        "<context>",
        # Every claim field was written by the extractor from fetched text: escaped like
        # the source itself (BD-26; code review RV-018)
        f"claim: {_e(statement)}",
        f"value as written: {_e(value_as_written or 'n/a')}",
        "labels:",
        f"  describes: {_e(labels.geography_name)} ({LEVEL_WORDS[labels.geography_level]})",
        f"  population: {_e(population(labels))}",
        f"  measure: {MEASURE_WORDS[labels.measure_type]}",
        f"  period: {_period(labels)}",
        f"  denominator: {_e(labels.denominator_text or 'not stated')}",
        # checker v3 (BD-22): the labels that set the threshold and the sample
        f"  case definition: {_e(labels.case_definition or 'not stated')}",
        f"  sample size: {labels.sample_size if labels.sample_size is not None else 'not stated'}",
        f"source: publisher {publisher_class}; "
        f"published {published.isoformat() if published else 'unknown'}",
        "</context>",
        "passage around the quote:",
        wrap_source(source_id, passage_text),
    ]
    for kind, text in label_passages:
        lines += [f"{LABEL_PASSAGE_TITLES[kind]}:", wrap_source(source_id, text)]
    return "\n".join(lines)
