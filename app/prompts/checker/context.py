"""Checker input: the restricted slice (LLD-3 §5.1, R-38, AT-07). Binding: the checker
receives the claim, its labels, its value and the code-located passage, and nothing
else: never the extractor's prompt or output, other claims, other sources, or the
slot question. `build_user_message` takes exactly these inputs, so nothing else can
reach it."""

from datetime import date

from app.domain.models import Labels
from app.prompts.safety import wrap_source

PASSAGE_MARGIN_CHARS = 600  # LLD-3 §5.1: the quote plus up to 600 characters either side


def passage(parsed_text: str, span_start: int, span_end: int) -> str:
    start = max(0, span_start - PASSAGE_MARGIN_CHARS)
    end = min(len(parsed_text), span_end + PASSAGE_MARGIN_CHARS)
    return parsed_text[start:end]


def _period(labels: Labels) -> str:
    start, end = labels.reference_start, labels.reference_end
    if labels.period_type.value == "publication_date_proxy" or not (start or end):
        return "not stated"
    if start and end and start != end:
        return f"{start.isoformat()} to {end.isoformat()}"
    return (end or start).isoformat()  # type: ignore[union-attr]


def build_user_message(
    statement: str,
    value_as_written: str | None,
    labels: Labels,
    source_id: str,
    publisher_class: str,
    published: date | None,
    passage_text: str,
) -> str:
    ages = (
        f"{labels.population_age_min}-{labels.population_age_max}"
        if labels.population_age_min is not None or labels.population_age_max is not None
        else "age not stated"
    )
    lines = [
        "<task>Decide whether the passage supports the claim exactly as labelled.</task>",
        "<context>",
        f"claim: {statement}",
        f"value as written: {value_as_written or 'n/a'}",
        "labels:",
        f"  describes: {labels.geography_level.value} — {labels.geography_name}",
        f"  population: {ages}, {labels.population_sex.value}, "
        f"{labels.population_group or 'general'}; setting: {labels.setting or 'not stated'}",
        f"  measure: {labels.measure_type.value}",
        f"  period: {_period(labels)}",
        f"  denominator: {labels.denominator_text or 'not stated'}",
        f"source: publisher {publisher_class}; "
        f"published {published.isoformat() if published else 'unknown'}",
        "</context>",
        wrap_source(source_id, passage_text),
    ]
    return "\n".join(lines)
