"""Planner input (LLD-3 §3.1), assembled by code. v2 (BD-14) adds the country's generic
government `site:` filters; a re-plan round lists each slot's earlier attempt. v3 (BD-15)
gives the number of queries per slot from config. v5 (BD-50) lists the sites that
refused access in each earlier attempt."""

from collections.abc import Sequence

from app.domain.models import CityIdentity, IndicatorDef, SlotDef


def build_user_message(
    city: CityIdentity,
    slots: Sequence[SlotDef],
    indicators: dict[str, IndicatorDef],
    round_no: int = 0,
    previous: Sequence[str] = (),
    government_sites: Sequence[str] = (),
    queries_per_slot: int = 2,
) -> str:
    place = ", ".join(p for p in (city.name, city.admin1_name, city.country_name) if p)
    lines = [
        "<task>Write web search queries to research the questions below for one city.</task>",
        "<context>",
        f"city: {place}",
        "language: en (this version searches in English only, BD-31)",
        f"round: {round_no}",
        f"queries_per_slot: {queries_per_slot}",
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


def previous_attempt(
    slot_id: str,
    status: str,
    queries: Sequence[str],
    note: str | None,
    refused: Sequence[str] = (),
) -> str:
    """One `previous_attempts` line (LLD-3 §3.1); `refused`: domains that blocked the
    slot's pages, never to be searched again (BD-50)."""
    tried = " | ".join(queries) or "none"
    line = f"{slot_id}: status {status}; queries tried: {tried}; note: {note or 'none'}"
    return line + f"; sites refusing access: {', '.join(refused) or 'none'}"


def fallback_queries(city: CityIdentity, slot: SlotDef) -> list[tuple[str, str]]:
    """LLD-2 §3.4: two template queries, in English (BD-31), when the planner gives the
    slot no usable plan; invents nothing."""
    return [
        (f"{slot.short_label} {city.name} {city.country_name}", "en"),
        (f"{city.name} {slot.short_label} survey report", "en"),
    ]
