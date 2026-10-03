"""brief_ready (LLD-2 §3.3): run summary, final status, run_finished. No external calls."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import EventType
from app.workflow.nodes._deps import deps
from app.workflow.state import RunState


async def brief_ready(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    run_id = state["run_id"]
    statuses = await d.relational.research.claim_statuses(run_id)
    reports = state.get("slot_reports", {})
    summary = {
        "claims": statuses,
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
