"""plan_slots (LLD-2 §3.3, LLD-3 §3): the planner writes queries; on failure, template
queries keep the run moving without inventing anything (§3.4)."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import EventType
from app.ports.errors import PortError
from app.prompts.loader import load_prompt
from app.prompts.planner import context
from app.prompts.planner.schema import PlannerOutput, validate
from app.workflow.budget import BudgetExhaustedError
from app.workflow.llm import call_role
from app.workflow.nodes._deps import deps
from app.workflow.state import PlannedQuery, RunState, SlotPlan


async def plan_slots(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    city = state["city"]
    slots = [d.slots[s] for s in state["slots_to_work"]]
    prompt = load_prompt("planner")
    user = context.build_user_message(city, slots, d.indicators, state.get("round", 0))
    slot_ids = {s.slot_id for s in slots}
    plans: dict[str, SlotPlan] = {}
    try:
        out = await call_role(
            d,
            "planner",
            prompt.system,
            user,
            PlannerOutput,
            problems=lambda o: validate(o, slot_ids, city.languages),
        )
        for s in out.parsed.slots:
            plans[s.slot_id] = SlotPlan(
                slot_id=s.slot_id,
                queries=[
                    PlannedQuery(text=q.text, lang=q.lang, purpose=q.purpose) for q in s.queries
                ],
            )
    except (PortError, BudgetExhaustedError):
        pass  # every slot without a plan gets the template below
    for slot in slots:
        if slot.slot_id not in plans:
            plans[slot.slot_id] = SlotPlan(
                slot_id=slot.slot_id,
                queries=[
                    PlannedQuery(text=t, lang=lang, purpose="template")
                    for t, lang in context.fallback_queries(city, slot)
                ],
                fallback=True,
            )
    for plan in plans.values():
        await d.events.emit(
            state["run_id"],
            EventType.SLOT_PLANNED,
            {
                "slot_id": plan.slot_id,
                "round": state.get("round", 0),
                "queries": [q.model_dump() for q in plan.queries],
            },
        )
    return {"plans": plans}
