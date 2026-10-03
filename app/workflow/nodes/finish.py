"""write, record_gate_gap, record_unsupported and slot_done (LLD-2 §3.2-3.3).

`write` records that supported claims are facts; graph edges arrive with D2-4, so the
`fact_written` event says `graph_edge: false` until then."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import EventType
from app.workflow.nodes._deps import deps
from app.workflow.state import SlotReport, SlotState


async def write(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    for claim_id in state.get("supported_claim_ids", []):
        claim, _ = await d.relational.research.claim_with_statistic(claim_id)
        await d.events.emit(
            state["run_id"],
            EventType.FACT_WRITTEN,
            {"claim_id": claim_id, "kind": claim.kind.value, "graph_edge": False},
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
    return {"slot_reports": {state["slot_id"]: report}}
