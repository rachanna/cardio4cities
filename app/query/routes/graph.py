"""R4 graph (LLD-5 §4.3-4.4): edges of the city partition for the slots' relation types,
mapped to claims through `graph_link`. A graph failure is an honest gap, never a
Postgres fallback (RD-06)."""

from app.query.routes import timed
from app.query.types import AskDeps, RouteResult, Understanding

GRAPH_TYPES = ("relationship", "change_over_time")


def runs_graph(u: Understanding) -> bool:
    """LLD-5 §4: relationship and change questions, and open ones naming an entity."""
    return u.question_type in GRAPH_TYPES or (u.question_type == "open" and bool(u.entity_mentions))


async def r4(deps: AskDeps, u: Understanding, entity_ids: list[str]) -> RouteResult:
    async def work(route: RouteResult) -> None:
        if not runs_graph(u):
            route.status, route.note = "skipped", "not a relationship question"
            return
        if not deps.graph_on:
            route.status, route.note = "skipped", "graph switched off (R-88)"
            return
        if deps.graph is None:
            route.status, route.note = "unavailable", "no graph store"
            return
        types = sorted({t.value for s in u.slot_ids for t in deps.slots[s].relation_types})
        include_ended = u.question_type == "change_over_time" or u.as_of is not None
        try:
            hits = await deps.graph.search_edges(
                deps.city_id, types, as_of=u.as_of, include_ended=include_ended, limit=50
            )
        except Exception as exc:  # honest abstention, never a Postgres fallback (RD-06)
            route.status, route.note = "unavailable", type(exc).__name__
            return
        if entity_ids:
            wanted = {
                e.graph_uuid for e in (await deps.relational.entities.get(entity_ids)).values()
            }
            named = [h for h in hits if {h.subject.uuid, h.object.uuid} & wanted]
            hits = named or hits  # a mention that resolved to nothing in the graph narrows nothing
        by_edge = await deps.relational.research.claims_for_edges([h.edge.uuid for h in hits])
        route.candidates = list(
            dict.fromkeys(c for h in hits for c in by_edge.get(h.edge.uuid, []))
        )

    return await timed(RouteResult("R4"), work)
