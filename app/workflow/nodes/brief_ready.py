"""brief_ready (LLD-2 §3.3): run summary, final status, run_finished.

Before the summary, each supported or contested claim whose graph write failed is
retried once (LLD-2 §3.3). The summary counts dropped claims by reason; the
`geography_unresolved` count is always present, so a city whose areas the gazetteer
cannot place shows it (D2-4)."""

from collections import Counter
from collections.abc import Iterable
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import ClaimStatus, EventType
from app.workflow.deps import RunDeps
from app.workflow.graph_writes import write_graph
from app.workflow.nodes._deps import deps
from app.workflow.state import RunState

EVENT_PAGE = 500
ALWAYS_COUNTED = ("geography_unresolved",)
RETRIED = frozenset({ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED})


def drop_counts(events: Iterable[dict[str, Any]]) -> dict[str, int]:
    """`claim_dropped` events by reason; the always-counted reasons appear even at 0."""
    counts = Counter(
        str(e["payload"].get("reason")) for e in events if e["type"] == EventType.CLAIM_DROPPED
    )
    return {**dict.fromkeys(ALWAYS_COUNTED, 0), **dict(sorted(counts.items()))}


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
    """Superseded claims are not retried: without their successor's date the edge would
    look current."""
    research = d.relational.research
    attempted = written = 0
    for claim_id in await research.claims_without_graph_link(run_id):
        claim, _ = await research.claim_with_statistic(claim_id)
        if claim.status not in RETRIED:
            continue
        attempted += 1
        written += await write_graph(d, claim_id)
    return {"attempted": attempted, "written": written}


async def brief_ready(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    run_id = state["run_id"]
    graph_retry = await _retry_graph(d, run_id)
    statuses = await d.relational.research.claim_statuses(run_id)
    reports = state.get("slot_reports", {})
    summary = {
        "claims": statuses,
        "dropped": drop_counts(await _all_events(d, run_id)),
        "graph_retry": graph_retry,
        "slots": {k: v.model_dump() for k, v in reports.items()},
        "budget": d.ledger.snapshot(),
    }
    status = "stopped_by_budget" if d.ledger.phase() == "exhausted" else "completed"
    await d.relational.runs.save_summary(run_id, summary)
    # The event first: a terminal status then always means run_finished is stored, which
    # the event stream relies on to close (LLD-4 §4).
    await d.events.emit(run_id, EventType.RUN_FINISHED, {"status": status, "summary": summary})
    await d.relational.runs.set_status(run_id, status)
    return {"finished": True}
