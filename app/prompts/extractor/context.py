"""Extractor input (LLD-3 §4.1), assembled by code. The source window is wrapped and
escaped by `safety.wrap_source`."""

from collections.abc import Sequence
from datetime import date

from app.domain.models import CityIdentity, IndicatorDef, SlotDef
from app.prompts.safety import wrap_source


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
        f'source: title "{title or "untitled"}"; publisher {publisher_class}; '
        f"published {published.isoformat() if published else 'unknown'};",
        f"        url {url}; window {window_index} of {window_count}",
        "</context>",
        wrap_source(source_id, window_text),
    ]
    return "\n".join(lines)
