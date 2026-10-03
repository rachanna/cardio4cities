"""coverage (LLD-2 §3.3, §11, R-79, AT-32): after each round, every slot of the run gets
exactly one status, its flags, a gap note from the templates, the queries tried (search
IDs), the sources checked and its best claims, stored in `slot_result` and streamed as
`slot_status`. It calls no external service, so it runs after a budget stop too.

Then the re-plan rule (§11.3): slots that qualify go back to `plan_slots` for another
round while the ledger is in its normal phase, priority slots first and only as many as
the searches left can serve (BD-15); otherwise the run moves on to `analytics`.
The ledger's counters are saved with the run each round, for a resume (BD-14)."""

from collections.abc import Iterable
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.badges import badges
from app.domain.models import Claim
from app.domain.ranking import Candidate, ranked
from app.domain.vocab import (
    SHOWABLE_STATUSES,
    ClaimKind,
    ClaimStatus,
    CrawlOutcome,
    EventType,
    PublisherClass,
    SlotStatus,
)
from app.domain.wording import language_name
from app.workflow.conflicts import sweep_statistics
from app.workflow.deps import RunDeps
from app.workflow.nodes._deps import deps
from app.workflow.rules.gap_notes import gap_note
from app.workflow.rules.slot_status import (
    replan_capacity,
    replan_order,
    should_replan,
    slot_flags,
    slot_status,
)
from app.workflow.state import RunState, SlotReport

UNCONFIRMED = frozenset({ClaimStatus.EXTRACTED, ClaimStatus.REFUTED, ClaimStatus.INSUFFICIENT})


def _union(lists: Iterable[list[str]]) -> list[str]:
    return list(dict.fromkeys(i for items in lists for i in items))


async def _flags(d: RunDeps, best: Claim | None, contested: set[str], slot_id: str) -> list[str]:
    if best is None:
        return []
    relation = (
        await d.relational.research.relation(best.claim_id)
        if best.kind is ClaimKind.RELATION
        else None
    )
    found = badges(
        best,
        d.slots[slot_id].accepted_levels,
        d.today(),
        d.badge,
        relation.relation_type if relation else None,
    )
    return sorted(f.value for f in slot_flags(best.claim_id, contested, found.main, found.others))


async def slot_result(
    d: RunDeps, run_id: str, slot_id: str, history: list[SlotReport], replans_used: int
) -> dict[str, Any]:
    """The `slot_result` row for one slot, from every round it was worked in."""
    slot = d.slots[slot_id]
    research = d.relational.research
    query_ids = _union(r.query_ids for r in history)
    fetched = _union(r.source_ids for r in history)
    rows = await research.slot_claims(run_id, slot_id)
    claims = [c for c, _ in rows]
    outcomes = [
        CrawlOutcome(o)
        for o in await d.relational.sources.crawl_outcomes(
            _union(r.crawl_decision_ids for r in history)
        )
    ]
    # An allowed page that was never fetched (the budget stopped it) is neither blocked
    # nor unreachable: only refusals and failures decide those statuses.
    refusals = [o for o in outcomes if o is not CrawlOutcome.ALLOWED]
    status = slot_status(slot, claims, len(fetched), refusals)
    allowed = len(outcomes) - len(refusals)
    unread = max(allowed - len(fetched), 0) if d.ledger.refused else 0
    showable = ranked(
        (Candidate(c, PublisherClass(cls)) for c, cls in rows if c.status in SHOWABLE_STATUSES),
        slot.accepted_levels,
    )
    best = showable[0].claim if showable else None
    queries = await research.queries(query_ids)
    checked = _union([fetched, [c.source_id for c in claims]])
    note = gap_note(
        status,
        best=best if status is SlotStatus.ANSWERED_WIDER_GEO else None,
        n_queries=len(queries),
        languages=list(dict.fromkeys(language_name(lang) for _, lang in queries)),
        n_sources=len(checked),
        crawl_outcomes=refusals,
        unconfirmed=sum(c.status in UNCONFIRMED for c in claims),
        unread=unread,
    )
    return {
        "slot_id": slot_id,
        "status": status.value,
        "flags": await _flags(d, best, await research.contested_claim_ids(run_id), slot_id),
        "replans_used": replans_used,
        "queries_tried": query_ids,  # search_query IDs (LLD-1 §2.7)
        "sources_checked": checked,
        "best_claim_ids": [c.claim.claim_id for c in showable],
        "gap_note": note,
    }


async def coverage(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    run_id, round_no = state["run_id"], state.get("round", 0)
    reports = state.get("slot_reports", {})
    replans = state.get("replans", {})
    worked = set(state.get("slots_to_work", []))
    # Conflicts across the whole run first, so flags and best claims see them (BD-19)
    await sweep_statistics(d, run_id)
    winding_down = d.ledger.phase() != "normal"
    again: list[str] = []
    for slot_id in state.get("all_slots", sorted(worked)):
        history = [r for r in reports.values() if r.slot_id == slot_id]
        result = await slot_result(d, run_id, slot_id, history, replans.get(slot_id, 0))
        await d.relational.runs.save_slot_result(run_id, result)
        if slot_id in worked:
            await d.events.emit(
                run_id,
                EventType.SLOT_STATUS,
                {
                    "slot_id": slot_id,
                    "round": round_no,
                    "status": result["status"],
                    "flags": result["flags"],
                    "gap_note": result["gap_note"],
                },
            )
        status = SlotStatus(result["status"])
        if should_replan(d.slots[slot_id], status, replans.get(slot_id, 0), winding_down, d.replan):
            again.append(slot_id)
    # Priority slots first, and only as many as the searches left can serve (BD-15)
    capacity = replan_capacity(d.ledger.searches, d.ledger.limits.searches, d.queries_per_slot)
    again = replan_order(again, d.replan.priority)[:capacity]
    await d.relational.runs.save_budget_used(run_id, d.ledger.snapshot())
    if not again:
        return {"slots_to_work": []}
    return {
        "slots_to_work": again,
        "round": round_no + 1,
        "replans": {s: replans.get(s, 0) + 1 for s in again},
    }


def route_after_coverage(state: RunState) -> str:
    """Sufficiency (AT-03): another round for the slots that qualify, or move on."""
    return "plan_slots" if state.get("slots_to_work") else "analytics"


async def analytics(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    """Graph centrality is a COULD item (LLD-2 §3.1): with `analytics.enabled = false` it
    is skipped; it is not built in this version."""
    return {}
