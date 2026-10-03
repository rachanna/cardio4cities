"""write, record_gate_gap, record_unsupported and slot_done (LLD-2 §3.2-3.3).

`write` puts each supported, contested or superseded claim of the slot into the graph
(one edge per claim, BD-11) and brings the retrieval indexes in line once its entities
exist (CHG-01: `search_tsv` includes entity names). A graph failure leaves the claim
supported in Postgres; `fact_written` says whether the edge was written."""

from datetime import date
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import ClaimStatus, EventType
from app.workflow.claim_index import sync
from app.workflow.graph_writes import apply_programme_status, write_graph
from app.workflow.nodes._deps import deps
from app.workflow.state import SlotReport, SlotState, report_key

IN_GRAPH = frozenset({ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED, ClaimStatus.SUPERSEDED})
FACTS = frozenset({ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED})


async def write(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    ended = state.get("ended", {})
    in_slot = set(state.get("claim_ids", []))
    ids = dict.fromkeys(
        [*state.get("supported_claim_ids", []), *(c for c in ended if c in in_slot)]
    )
    for claim_id in ids:
        claim, _ = await d.relational.research.claim_with_statistic(claim_id)
        if claim.status not in IN_GRAPH:
            continue
        at = date.fromisoformat(ended[claim_id]) if claim_id in ended else None
        written = await write_graph(d, claim_id, at)
        await sync(d, claim_id)
        if claim.status in FACTS:
            await apply_programme_status(d, claim)
            await d.events.emit(
                state["run_id"],
                EventType.FACT_WRITTEN,
                {"claim_id": claim_id, "kind": claim.kind.value, "graph_edge": written},
            )
    return {}


async def record_gate_gap(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    """Every decision is already stored with its reason; the gap note comes with coverage."""
    return {}


async def record_unsupported(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    """Verdicts and their reasons are already stored; nothing becomes a fact."""
    return {}


def slot_done(state: SlotState) -> dict[str, Any]:
    report = SlotReport(
        slot_id=state["slot_id"],
        round=state.get("round", 0),
        query_ids=state.get("query_ids", []),
        source_ids=state.get("source_ids", []),
        crawl_decision_ids=state.get("crawl_decision_ids", []),
        claim_ids=state.get("claim_ids", []),
        supported_claim_ids=state.get("supported_claim_ids", []),
        error=state.get("error"),
    )
    return {"slot_reports": {report_key(state["slot_id"], report.round): report}}
