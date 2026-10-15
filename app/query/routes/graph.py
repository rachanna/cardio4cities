"""R4 graph (LLD-5 §4.3-4.4, E-07): the latest run's edges of the asked relation types,
ranked by Graphiti's hybrid search on the question, mapped to claims through `graph_link`.
A graph failure is an honest gap, never a Postgres fallback (RD-06).

Shaped by the question (BD-57): Postgres decides which edges are in scope (the run's,
through `graph_link`); the structural search returns every one of them of the asked types
and dates, so nothing in scope is lost; Graphiti then ranks them by meaning, around the
named entity when there is one. Edges its similarity cut-off leaves unranked follow the
ranked ones, newest first."""

from collections.abc import Sequence

from app.ports.graph import GraphEdgeHit
from app.query.routes import timed
from app.query.types import AskDeps, RouteResult, Understanding

GRAPH_TYPES = ("relationship", "change_over_time")


def runs_graph(u: Understanding) -> bool:
    """LLD-5 §4: relationship and change questions, and open ones naming an entity."""
    return u.question_type in GRAPH_TYPES or (u.question_type == "open" and bool(u.entity_mentions))


def ranked_first(
    ranked: Sequence[GraphEdgeHit], structural: Sequence[GraphEdgeHit]
) -> list[GraphEdgeHit]:
    """Graphiti's order for the edges it ranked, then every other in-scope edge in the
    structural order: ranking reorders, it never drops (E-07)."""
    seen = {h.edge.uuid for h in ranked}
    return [*ranked, *(h for h in structural if h.edge.uuid not in seen)]


async def r4(deps: AskDeps, u: Understanding, entity_ids: list[str], question: str) -> RouteResult:
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
        in_run = await deps.relational.research.run_edge_uuids(deps.run_id)
        wanted: set[str] = set()
        if entity_ids:
            wanted = {
                e.graph_uuid for e in (await deps.relational.entities.get(entity_ids)).values()
            }
        try:
            structural = await deps.graph.search_edges(
                deps.city_id,
                types,
                as_of=u.as_of,
                include_ended=include_ended,
                limit=max(len(in_run), 1),
                edge_uuids=in_run,
            )
            center = next(
                (n for h in structural for n in (h.subject.uuid, h.object.uuid) if n in wanted),
                None,
            )
            ranked = (
                await deps.graph.search_edges(
                    deps.city_id,
                    types,
                    as_of=u.as_of,
                    include_ended=include_ended,
                    query=question,
                    limit=len(structural),
                    edge_uuids=[h.edge.uuid for h in structural],
                    center_uuid=center,
                )
                if structural
                else []
            )
        except Exception as exc:  # honest abstention, never a Postgres fallback (RD-06)
            route.status, route.note = "unavailable", type(exc).__name__
            return
        hits = ranked_first(ranked, structural)
        if wanted:
            named = [h for h in hits if {h.subject.uuid, h.object.uuid} & wanted]
            hits = named or hits  # a mention that resolved to nothing in the graph narrows nothing
        route.note = f"{len(ranked)} of {len(structural)} edges ranked by meaning" + (
            " around the named entity" if center else ""
        )
        by_edge = await deps.relational.research.claims_for_edges([h.edge.uuid for h in hits])
        route.candidates = list(
            dict.fromkeys(c for h in hits for c in by_edge.get(h.edge.uuid, []))
        )

    return await timed(RouteResult("R4"), work)
