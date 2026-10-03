"""crawl_gate (LLD-2 §9.1): decides before any content request; every decision is stored
and streamed, so the panel sees blocked sources and why (R-03, R-40)."""

from datetime import UTC, datetime
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.models import CrawlDecision
from app.domain.vocab import CrawlOutcome, EventType
from app.workflow.budget import BudgetExhaustedError
from app.workflow.collection import GateDecision
from app.workflow.deps import RunDeps
from app.workflow.ids import new_id
from app.workflow.nodes._deps import deps
from app.workflow.state import SlotState


async def record_decision(d: RunDeps, run_id: str, decision: GateDecision) -> str:
    decision_id = new_id("cd")
    reason = decision.reason
    if decision.usage_preferences and decision.outcome is CrawlOutcome.ALLOWED:
        reason += f"; stated AI-use preferences recorded: {decision.usage_preferences}"
    await d.relational.sources.add_crawl_decision(
        CrawlDecision(
            decision_id=decision_id,
            run_id=run_id,
            url=decision.url,
            domain=decision.domain,
            outcome=decision.outcome,
            rule=decision.rule,
            reason=reason,
            robots_http_status=decision.robots_http_status,
            decided_at=datetime.now(UTC),
        )
    )
    await d.events.emit(
        run_id,
        EventType.CRAWL_DECISION,
        {
            "url": decision.url,
            "domain": decision.domain,
            "outcome": decision.outcome.value,
            "reason": reason,
        },
    )
    return decision_id


async def crawl_gate(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    allowed = []
    decision_ids = []
    for candidate in state.get("candidates", []):
        try:
            decision = await d.collector.gate(candidate.url)
        except BudgetExhaustedError:
            break
        decision_ids.append(await record_decision(d, state["run_id"], decision))
        if decision.outcome is CrawlOutcome.ALLOWED:
            allowed.append(candidate)
    return {"allowed": allowed, "crawl_decision_ids": decision_ids}


def route_after_gate(state: SlotState) -> str:
    return "fetch_parse" if state.get("allowed") else "record_gate_gap"
