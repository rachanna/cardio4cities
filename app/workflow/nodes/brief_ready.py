"""brief_ready (LLD-2 §3.3): run summary, final status, run_finished.

Before the summary, each supported or contested claim whose graph write failed is
retried once (LLD-2 §3.3). The summary (R-84, AT-38) shows claims by outcome, dropped
claims by reason (`geography_unresolved` always present, D2-4), sources blocked,
unreachable and unreadable by reason, slots by status, tokens and cost per model, and
busy time per stage beside the run's wall clock (D2-5)."""

from collections import Counter
from collections.abc import Callable, Iterable
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import ClaimStatus, EventType, ParseOutcome
from app.workflow.deps import RunDeps
from app.workflow.graph_writes import end_edge, mark_edge, write_graph
from app.workflow.nodes._deps import deps
from app.workflow.state import RunState

EVENT_PAGE = 500
ALWAYS_COUNTED = ("geography_unresolved",)
RETRIED = frozenset({ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED, ClaimStatus.SUPERSEDED})


def drop_counts(events: Iterable[dict[str, Any]]) -> dict[str, int]:
    """`claim_dropped` events by reason; the always-counted reasons appear even at 0."""
    counts = Counter(
        str(e["payload"].get("reason")) for e in events if e["type"] == EventType.CLAIM_DROPPED
    )
    return {**dict.fromkeys(ALWAYS_COUNTED, 0), **dict(sorted(counts.items()))}


def source_counts(outcomes: dict[str, dict[str, int]]) -> dict[str, Any]:
    """Crawl decisions per URL by outcome, and stored pages by parse outcome."""
    crawl, parse = outcomes.get("crawl", {}), outcomes.get("parse", {})

    def pick(counts: dict[str, int], keep: Callable[[str], bool]) -> dict[str, int]:
        return {k: n for k, n in sorted(counts.items()) if keep(k)}

    return {
        "read": parse.get(ParseOutcome.PARSED.value, 0),
        "blocked": pick(crawl, lambda o: o.startswith("blocked")),
        "unreachable": pick(crawl, lambda o: o.startswith("unreachable") or o == "rate_limited"),
        "unreadable": pick(parse, lambda o: o != ParseOutcome.PARSED.value),
    }


def summarise(
    statuses: dict[str, int],
    dropped: dict[str, int],
    sources: dict[str, Any],
    slot_rows: list[dict[str, Any]],
    budget: dict[str, Any],
    busy_ms: dict[str, int],
    graph_retry: dict[str, int],
) -> dict[str, Any]:
    """The run summary (AT-38). `claims` counts claim rows by status plus the dropped
    claims, which have no row (BD-09)."""
    by_model = budget.get("by_model", {})
    return {
        "claims": {**dict(sorted(statuses.items())), "dropped": sum(dropped.values())},
        "dropped": dropped,
        "sources": sources,
        "slots": dict(sorted(Counter(r["status"] for r in slot_rows).items())),
        "slot_results": {
            r["slot_id"]: {
                "status": r["status"],
                "flags": list(r["flags"]),
                "replans_used": r["replans_used"],
                "gap_note": r["gap_note"],
            }
            for r in slot_rows
        },
        "models": by_model,
        "cost_usd": round(sum(m["cost_micro_usd"] for m in by_model.values()) / 1_000_000, 4),
        "time": {"wall_clock_ms": budget.get("wall_clock_ms", 0), "busy_ms": busy_ms},
        "graph_retry": graph_retry,
        "budget": budget,
    }


async def _all_events(d: RunDeps, run_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    while True:
        page = await d.relational.runs.events_after(
            run_id, events[-1]["seq"] if events else 0, EVENT_PAGE
        )
        events += page
        if len(page) < EVENT_PAGE:
            return events


async def _retry_graph(d: RunDeps, run_id: str) -> dict[str, int]:
    """Bring the graph in line with Postgres once more (BD-19): missing edges (a
    superseded claim's is written ended on its stored date), edges a superseded claim
    left current, and contested marks that did not reach the graph."""
    research = d.relational.research
    attempted = written = 0
    for claim_id in await research.claims_without_graph_link(run_id):
        claim, _ = await research.claim_with_statistic(claim_id)
        if claim.status not in RETRIED:
            continue
        attempted += 1
        written += await write_graph(d, claim_id)
    ended = 0
    for claim_id in await research.superseded_live_links(run_id):
        relation = await research.relation(claim_id)
        if relation is not None and relation.superseded_on is not None:
            await end_edge(d, claim_id, relation.superseded_on)
            ended += 1
    for claim_id in await research.contested_links(run_id):
        await mark_edge(d, claim_id, ClaimStatus.CONTESTED.value)
    return {"attempted": attempted, "written": written, "ended": ended}


async def brief_ready(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    run_id = state["run_id"]
    graph_retry = await _retry_graph(d, run_id)
    budget = d.ledger.snapshot()
    summary = summarise(
        await d.relational.research.claim_statuses(run_id),
        drop_counts(await _all_events(d, run_id)),
        source_counts(await d.relational.sources.outcome_counts(run_id)),
        await d.relational.runs.slot_results(run_id),
        budget,
        d.stages.snapshot(),
        graph_retry,
    )
    await d.relational.runs.save_budget_used(run_id, budget)
    # A run is stopped by its budget when the budget refused a call it wanted to make
    status = "stopped_by_budget" if budget["refused"] else "completed"
    await d.relational.runs.save_summary(run_id, summary)
    # The event first: a terminal status then always means run_finished is stored, which
    # the event stream relies on to close (LLD-4 §4).
    await d.events.emit(run_id, EventType.RUN_FINISHED, {"status": status, "summary": summary})
    await d.relational.runs.set_status(run_id, status)
    return {"finished": True}
