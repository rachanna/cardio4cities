"""Planner output (LLD-3 §3.3) and its code validation (§3.4). Length limits are
checked here, not in the schema sent to the provider (strict schema modes reject them)."""

import re

from pydantic import BaseModel

SITE_FILTER = re.compile(r"\bsite:(\S+)", re.IGNORECASE)
MAX_QUERY_CHARS = 120
MAX_PURPOSE_CHARS = 80
QUERIES_PER_SLOT = (2, 3)


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


def validate(
    output: PlannerOutput,
    slot_ids: set[str],
    languages: list[str],
    earlier_queries: set[str] = frozenset(),  # type: ignore[assignment]
    sites: set[str] = frozenset(),  # type: ignore[assignment]
) -> list[str]:
    """Problems to send back in a repair request; empty when the output is usable.
    Removes queries already tried on an earlier round (§3.4) in place. A `site:` filter
    must be one of `sites`, the government filters the planner was given (v2)."""
    problems = []
    if {s.slot_id for s in output.slots} != slot_ids:
        problems.append(f"return exactly these slot ids: {sorted(slot_ids)}")
    allowed_langs = set(languages) | {"en"}
    primary = languages[0] if languages else "en"
    earlier = {_key(q) for q in earlier_queries}
    for slot in output.slots:
        slot.queries = [q for q in slot.queries if _key(q.text) not in earlier]
        low, high = QUERIES_PER_SLOT
        if not low - 1 <= len(slot.queries) <= high:
            problems.append(f"{slot.slot_id}: give {low} to {high} new queries")
        for q in slot.queries:
            if q.lang not in allowed_langs:
                problems.append(
                    f"{slot.slot_id}: language {q.lang!r} is not one of {sorted(allowed_langs)}"
                )
            if len(q.text) > MAX_QUERY_CHARS or len(q.purpose) > MAX_PURPOSE_CHARS:
                problems.append(f"{slot.slot_id}: keep queries under 15 words")
            for found in SITE_FILTER.findall(q.text):
                if f"site:{found.lower()}" not in {x.lower() for x in sites}:
                    problems.append(f"{slot.slot_id}: site:{found} is not in government_sites")
        if primary != "en" and not any(q.lang == primary for q in slot.queries):
            problems.append(f"{slot.slot_id}: include at least one query in {primary!r}")
    return problems
