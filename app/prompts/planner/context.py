"""Planner input (LLD-3 §3.1), assembled by code. v2 (BD-14) adds the country's generic
government `site:` filters; a re-plan round lists each slot's earlier attempt."""

from collections.abc import Sequence

from app.domain.models import CityIdentity, IndicatorDef, SlotDef


def build_user_message(
    city: CityIdentity,
    slots: Sequence[SlotDef],
    indicators: dict[str, IndicatorDef],
    round_no: int = 0,
    previous: Sequence[str] = (),
    government_sites: Sequence[str] = (),
) -> str:
    place = ", ".join(p for p in (city.name, city.admin1_name, city.country_name) if p)
    lines = [
        "<task>Write web search queries to research the questions below for one city.</task>",
        "<context>",
        f"city: {place}",
        f"languages: {', '.join(city.languages) or 'en'}",
        f"round: {round_no}",
        f"government_sites: {', '.join(government_sites) or 'none'}",
        "slots:",
    ]
    for slot in slots:
        names = ", ".join(indicators[c].name for c in slot.indicator_codes if c in indicators)
        lines.append(
            f"- {slot.slot_id}: {slot.question} (looking for: {slot.answer_kind.value}"
            + (f"; indicators: {names}" if names else "")
            + ")"
        )
    if round_no > 0 and previous:
        lines.append("previous_attempts:")
        lines += [f"- {p}" for p in previous]
    lines.append("</context>")
    return "\n".join(lines)


def previous_attempt(slot_id: str, status: str, queries: Sequence[str], note: str | None) -> str:
    """One `previous_attempts` line (LLD-3 §3.1)."""
    tried = " | ".join(queries) or "none"
    return f"{slot_id}: status {status}; queries tried: {tried}; note: {note or 'none'}"


def fallback_queries(city: CityIdentity, slot: SlotDef) -> list[tuple[str, str]]:
    """LLD-2 §3.4: template queries when the planner fails twice; invents nothing."""
    queries = [(f"{slot.short_label} {city.name} {city.country_name}", "en")]
    return queries
