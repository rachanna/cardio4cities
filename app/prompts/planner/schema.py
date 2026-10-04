"""Planner output (LLD-3 §3.3) and its code validation (§3.4). Length limits are
checked here, not in the schema sent to the provider (strict schema modes reject them)."""

import re

from pydantic import BaseModel

SITE_FILTER = re.compile(r"\bsite:(\S+)", re.IGNORECASE)
MAX_QUERY_CHARS = 120
MAX_PURPOSE_CHARS = 80


class PlannedQuery(BaseModel):
    text: str
    lang: str  # ISO 639-1
    purpose: str


class SlotQueries(BaseModel):
    slot_id: str
    queries: list[PlannedQuery]


class PlannerOutput(BaseModel):
    slots: list[SlotQueries]


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def slot_problems(
    slot: SlotQueries,
    earlier_queries: set[str] = frozenset(),  # type: ignore[assignment]
    sites: set[str] = frozenset(),  # type: ignore[assignment]
    per_slot: int = 2,
) -> list[str]:
    """One slot's problems; empty when its plan is usable. Removes queries already tried
    on an earlier round (§3.4) in place. Every query is in English (BD-31); a `site:`
    filter must be one of `sites`, the government filters the planner was given (v2)."""
    problems = []
    earlier = {_key(q) for q in earlier_queries}
    slot.queries = [q for q in slot.queries if _key(q.text) not in earlier]
    if len(slot.queries) != per_slot:  # plan.queries_per_slot (BD-15)
        problems.append(f"{slot.slot_id}: give exactly {per_slot} new queries")
    for q in slot.queries:
        if q.lang != "en":
            problems.append(f'{slot.slot_id}: write every query in English (lang "en")')
        if len(q.text) > MAX_QUERY_CHARS or len(q.purpose) > MAX_PURPOSE_CHARS:
            problems.append(
                f"{slot.slot_id}: keep queries to {MAX_QUERY_CHARS} characters and purposes"
                f" to {MAX_PURPOSE_CHARS}"
            )
        for found in SITE_FILTER.findall(q.text):
            if f"site:{found.lower()}" not in {x.lower() for x in sites}:
                problems.append(f"{slot.slot_id}: site:{found} is not in government_sites")
    return problems


def validate(
    output: PlannerOutput,
    slot_ids: set[str],
    earlier_queries: set[str] = frozenset(),  # type: ignore[assignment]
    sites: set[str] = frozenset(),  # type: ignore[assignment]
    per_slot: int = 2,
) -> list[str]:
    """Problems to send back in a repair request; empty when the output is usable."""
    problems = []
    if {s.slot_id for s in output.slots} != slot_ids:
        problems.append(f"return exactly these slot ids: {sorted(slot_ids)}")
    for slot in output.slots:
        problems += slot_problems(slot, earlier_queries, sites, per_slot)
    return problems


def usable_slots(
    raw: str,
    slot_ids: set[str],
    earlier_queries: set[str] = frozenset(),  # type: ignore[assignment]
    sites: set[str] = frozenset(),  # type: ignore[assignment]
    per_slot: int = 2,
) -> list[SlotQueries]:
    """After a failed repair, the slots of the last output that are usable on their own
    (code review RV-057): one slot's problem no longer sends every slot to the template."""
    try:
        output = PlannerOutput.model_validate_json(raw)
    except ValueError:
        return []
    kept: dict[str, SlotQueries] = {}
    for slot in output.slots:
        usable = slot.slot_id in slot_ids and slot.slot_id not in kept
        if usable and not slot_problems(slot, earlier_queries, sites, per_slot):
            kept[slot.slot_id] = slot
    return list(kept.values())
