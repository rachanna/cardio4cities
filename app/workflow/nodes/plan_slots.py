"""plan_slots (LLD-2 §3.3, LLD-3 §3): the planner writes queries; on failure, template
queries keep the run moving without inventing anything (§3.4).

On a re-plan round (§11.3) the planner sees each slot's status, the queries already
tried and the gap note; queries tried before are removed, from the planner's output and
from the templates alike. A slot left with no new query is not searched again."""

import re
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import EventType
from app.ports.errors import LLMOutputValidationError, PortError
from app.prompts.loader import load_prompt
from app.prompts.planner import context
from app.prompts.planner.schema import PlannerOutput, usable_slots, validate
from app.workflow.budget import BudgetExhaustedError
from app.workflow.llm import call_role
from app.workflow.nodes._deps import deps
from app.workflow.rules.selection import government_sites
from app.workflow.state import PlannedQuery, RunState, SlotPlan


def _key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


async def plan_slots(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    city, round_no = state["city"], state.get("round", 0)
    slots = [d.slots[s] for s in state["slots_to_work"]]
    slot_ids = {s.slot_id for s in slots}
    earlier: set[str] = set()
    previous: list[str] = []
    if round_no > 0:
        reports = state.get("slot_reports", {}).values()
        for row in await d.relational.runs.slot_results(state["run_id"]):
            if row["slot_id"] in slot_ids:
                texts = [t for t, _ in await d.relational.research.queries(row["queries_tried"])]
                earlier |= set(texts)
                decisions = [
                    i for r in reports if r.slot_id == row["slot_id"] for i in r.crawl_decision_ids
                ]
                refused = await d.relational.sources.refused_domains(decisions)
                previous.append(
                    context.previous_attempt(
                        row["slot_id"], row["status"], texts, row["gap_note"], refused
                    )
                )
    sites = government_sites(d.publishers, city.country_iso2)
    prompt = load_prompt("planner")
    user = context.build_user_message(
        city, slots, d.indicators, round_no, previous, sites, d.queries_per_slot
    )
    plans: dict[str, SlotPlan] = {}
    accepted = []
    try:
        out = await call_role(
            d,
            "planner",
            prompt.system,
            user,
            PlannerOutput,
            problems=lambda o: validate(o, slot_ids, earlier, set(sites), d.queries_per_slot),
        )
        accepted = out.parsed.slots
    except LLMOutputValidationError as exc:  # repaired once and still not all usable
        accepted = usable_slots(exc.raw_text, slot_ids, earlier, set(sites), d.queries_per_slot)
    except (PortError, BudgetExhaustedError):
        pass  # every slot without a plan gets the template below
    if accepted:
        for s in accepted:
            plans[s.slot_id] = SlotPlan(
                slot_id=s.slot_id,
                round=round_no,
                queries=[
                    PlannedQuery(text=q.text, lang=q.lang, purpose=q.purpose) for q in s.queries
                ],
            )
    tried = {_key(q) for q in earlier}
    for slot in slots:
        if slot.slot_id not in plans:
            queries = [
                PlannedQuery(text=t, lang=lang, purpose="template")
                for t, lang in context.fallback_queries(city, slot)
                if _key(t) not in tried
            ]
            if queries:
                plans[slot.slot_id] = SlotPlan(
                    slot_id=slot.slot_id, queries=queries, fallback=True, round=round_no
                )
    for plan in plans.values():
        await d.events.emit(
            state["run_id"],
            EventType.SLOT_PLANNED,
            {
                "slot_id": plan.slot_id,
                "round": round_no,
                "queries": [q.model_dump() for q in plan.queries],
            },
        )
    return {"plans": plans}
