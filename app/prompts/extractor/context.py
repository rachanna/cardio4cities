"""Extractor input (LLD-3 §4.1), assembled by code. The source window is wrapped and
escaped by `safety.wrap_source`."""

from collections.abc import Sequence
from datetime import date

from app.domain.models import CityIdentity, IndicatorDef, SlotDef
from app.domain.vocab import RELATION_PAIRS
from app.prompts.safety import escape_untrusted, wrap_source


def _relation_lines() -> list[str]:
    """The relation types and the entity types each joins (LLD-3 §4.1): a pair not listed
    is dropped by code, so the model is told (code review RV-056)."""
    return [
        f"- {kind.value}: " + "; ".join(f"{a.value} -> {b.value}" for a, b in sorted(pairs))
        for kind, pairs in RELATION_PAIRS.items()
        if kind.value != "MEASURED_IN"  # written by code from statistics, never extracted
    ]


def build_user_message(
    city: CityIdentity,
    slots: Sequence[SlotDef],
    indicators: Sequence[IndicatorDef],
    source_id: str,
    title: str | None,
    publisher_class: str,
    published: date | None,
    url: str,
    window_text: str,
    window_index: int,
    window_count: int,
) -> str:
    place = ", ".join(p for p in (city.name, city.admin1_name, city.country_name) if p)
    lines = [
        "<task>Extract claims from the source that answer the questions below.</task>",
        "<context>",
        f"city: {place}",
        "slots:",
        *[f"- {s.slot_id}: {s.question} (kind: {s.answer_kind.value})" for s in slots],
        "indicators:",
        *[f"- {i.code}: {i.name}." + (f" {i.notes}" if i.notes else "") for i in indicators],
        "- OTHER: any other number relevant to the slot.",
        "relation types (subject -> object):",
        *_relation_lines(),
        # The title and URL come from the page and the search result: escaped (RV-018)
        f'source: title "{escape_untrusted(title or "untitled")}"; publisher {publisher_class}; '
        f"published {published.isoformat() if published else 'unknown'};",
        f"        url {escape_untrusted(url)}; window {window_index} of {window_count}",
        "</context>",
        wrap_source(source_id, window_text),
    ]
    return "\n".join(lines)
