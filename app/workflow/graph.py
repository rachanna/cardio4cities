"""The LangGraph workflow (LLD-2 §3): a main graph that fans out one slot subgraph per
slot. The conditional edges are the routing points the rendered graph shows (AT-03):
the crawl decision, the verdict and sufficiency (coverage: re-plan or move on).

Every node adds its busy time to its stage (AT-38). With a checkpointer (D2-5, BD-14),
each step is saved, so a run stopped by a restart resumes where it was."""

from collections.abc import Awaitable
from typing import Any, Protocol

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from app.workflow.budget import BudgetExhaustedError
from app.workflow.nodes._deps import deps
from app.workflow.nodes.brief_ready import brief_ready
from app.workflow.nodes.consistency import consistency
from app.workflow.nodes.coverage import analytics, coverage, route_after_coverage
from app.workflow.nodes.crawl_gate import crawl_gate, route_after_gate
from app.workflow.nodes.extract import extract
from app.workflow.nodes.fetch_parse import fetch_parse
from app.workflow.nodes.finish import record_gate_gap, record_unsupported, slot_done, write
from app.workflow.nodes.match_quotes import match_quotes, route_after_match
from app.workflow.nodes.plan_slots import plan_slots
from app.workflow.nodes.resolve_city import resolve_city
from app.workflow.nodes.search import search
from app.workflow.nodes.select_sources import select_sources
from app.workflow.nodes.verify import route_after_verify, verify
from app.workflow.nodes.wave0 import wave0
from app.workflow.problems import step_failed
from app.workflow.state import RunState, SlotOutput, SlotState


class SlotNode(Protocol):
    def __call__(self, state: SlotState, config: RunnableConfig) -> Awaitable[dict[str, Any]]: ...


class RunNode(Protocol):
    def __call__(self, state: RunState, config: RunnableConfig) -> Awaitable[dict[str, Any]]: ...


def guarded(name: str, node: SlotNode) -> SlotNode:
    """One slot's failure never stops the run: the error goes on the slot report and the
    following nodes see empty inputs (LLD-2 §17). Budget exhaustion is not an error."""

    async def run(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
        clock = deps(config).stages
        started = clock.start()
        try:
            return await node(state, config)
        except BudgetExhaustedError:
            return {}
        except Exception as exc:  # recorded on the slot report and stored (BD-21)
            await step_failed(deps(config), state, name, None, exc)
            return {"error": f"{name}: {type(exc).__name__}"}
        finally:
            clock.stop(name, started)

    run.__name__ = name
    return run


def timed(name: str, node: RunNode) -> RunNode:
    async def run(state: RunState, config: RunnableConfig) -> dict[str, Any]:
        clock = deps(config).stages
        started = clock.start()
        try:
            return await node(state, config)
        finally:
            clock.stop(name, started)

    run.__name__ = name
    return run


def build_slot_graph() -> CompiledStateGraph[Any, Any, Any, Any]:
    g = StateGraph(SlotState, output_schema=SlotOutput)
    for name, node in (
        ("search", search),
        ("select_sources", select_sources),
        ("crawl_gate", crawl_gate),
        ("record_gate_gap", record_gate_gap),
        ("fetch_parse", fetch_parse),
        ("extract", extract),
        ("match_quotes", match_quotes),
        ("verify", verify),
        ("record_unsupported", record_unsupported),
        ("consistency", consistency),
        ("write", write),
    ):
        g.add_node(name, guarded(name, node))
    g.add_node("slot_done", slot_done)
    g.add_edge(START, "search")
    g.add_edge("search", "select_sources")
    g.add_edge("select_sources", "crawl_gate")
    g.add_conditional_edges("crawl_gate", route_after_gate, ["fetch_parse", "record_gate_gap"])
    g.add_edge("record_gate_gap", "slot_done")
    g.add_edge("fetch_parse", "extract")
    g.add_edge("extract", "match_quotes")
    g.add_conditional_edges("match_quotes", route_after_match, ["verify", "slot_done"])
    g.add_conditional_edges("verify", route_after_verify, ["consistency", "record_unsupported"])
    g.add_edge("record_unsupported", "slot_done")
    g.add_edge("consistency", "write")
    g.add_edge("write", "slot_done")
    g.add_edge("slot_done", END)
    return g.compile()


def fan_out(state: RunState) -> list[Send] | str:
    """One slot subgraph per slot with a plan for this round; none left: to coverage."""
    round_no = state.get("round", 0)
    plans = state.get("plans", {})
    sends = [
        Send(
            "slot_subgraph",
            {
                "run_id": state["run_id"],
                "city": state["city"],
                "slot_id": slot_id,
                "round": round_no,
                "plan": plans[slot_id],
            },
        )
        for slot_id in state["slots_to_work"]
        if slot_id in plans and plans[slot_id].round == round_no
    ]
    return sends or "coverage"


def build_graph(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    g = StateGraph(RunState)
    g.add_node("resolve_city", resolve_city)
    g.add_node("wave0", timed("wave0", wave0))
    g.add_node("plan_slots", timed("plan_slots", plan_slots))
    g.add_node("slot_subgraph", build_slot_graph())
    g.add_node("coverage", timed("coverage", coverage))
    g.add_node("analytics", analytics)
    g.add_node("brief_ready", brief_ready)  # writes the summary: not timed by it
    g.add_edge(START, "resolve_city")
    # Wave 0 runs alongside planning, in the same step (BD-27): its official-API calls
    # need no plan, and coverage meets its figures from the first round
    g.add_edge("resolve_city", "wave0")
    g.add_edge("resolve_city", "plan_slots")
    g.add_edge("wave0", END)
    g.add_conditional_edges("plan_slots", fan_out, ["slot_subgraph", "coverage"])
    g.add_edge("slot_subgraph", "coverage")
    g.add_conditional_edges("coverage", route_after_coverage, ["plan_slots", "analytics"])
    g.add_edge("analytics", "brief_ready")
    g.add_edge("brief_ready", END)
    return g.compile(checkpointer=checkpointer)
