"""resolve_city (LLD-2 §3.3): the city row exists (created by the API); start the run.
The city also becomes its Place entity, so every edge into it meets at one node (LLD-2 §6)."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import EventType
from app.workflow.nodes._deps import deps
from app.workflow.state import RunState


async def resolve_city(state: RunState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    city = state["city"]
    await d.relational.runs.set_status(state["run_id"], "running")
    await d.entities.ensure_city(city)
    await d.events.emit(
        state["run_id"],
        EventType.RUN_STARTED,
        {"run_id": state["run_id"], "city_id": city.city_id, "budget": d.ledger.limits.__dict__},
    )
    await d.events.emit(state["run_id"], EventType.IDENTITY_CONFIRMED, city.model_dump(mode="json"))
    return {}
