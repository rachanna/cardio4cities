"""GraphPort over Graphiti on Neo4j (LLD-1 §6, BD-11).

Writes save our own nodes and edges through Graphiti's model classes
(`EntityNode.save`, `EntityEdge.save`) with our embeddings: spike S-1 showed that
`add_triplet` asks a model to deduplicate, re-date and invalidate edges, and lost claim
IDs. So no Graphiti model call is ever made: its model client refuses every call.
Reads use Graphiti's hybrid search (BM25 + vectors, reciprocal rank fusion) with its
edge-type and date filters, or plain Cypher when there is no query text.

Supersession is decided by code and applied here only as `invalid_at`; nothing is
deleted (R-44, R-60). Any relation pair outside LLD-1 §6.2 is refused before it
reaches the graph.
"""

import logging
import os
from datetime import UTC, date, datetime
from typing import Any

os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"  # before graphiti_core is imported

from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.edges import EntityEdge
from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.errors import GroupsEdgesNotFoundError, GroupsNodesNotFoundError
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import (
    ComparisonOperator,
    DateFilter,
    SearchFilters,
)

from app.domain.vocab import RELATION_PAIRS, EntityType, RelationType
from app.ports.embeddings import EmbeddingsPort
from app.ports.graph import GraphEdge, GraphEdgeHit, GraphEntity, GraphExport
from app.settings import Settings

# Graphiti's queries read properties some edges never set; the server's notices are noise
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

# Properties Graphiti returns inside an edge's attributes that are not ours
_EDGE_FIELDS = frozenset(
    {
        "uuid",
        "source_uuid",
        "target_uuid",
        "name",
        "group_id",
        "fact",
        "fact_embedding",
        "episodes",
        "created_at",
        "expired_at",
        "valid_at",
        "invalid_at",
        "reference_time",
    }
)


class GraphWriteRefused(ValueError):
    """A relation pair outside LLD-1 §6.2."""


class NoModel(LLMClient):
    """Graph writes and reads never call a model (BD-11); any attempt is a bug."""

    def __init__(self) -> None:
        super().__init__(LLMConfig(api_key="unused", model="none"))

    async def generate_response(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError(f"Graphiti asked for a model call ({kwargs.get('prompt_name')})")

    async def _generate_response(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("Graphiti asked for a model call")


class NoRerank(CrossEncoderClient):
    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(p, 1.0) for p in passages]


class PortEmbedder(EmbedderClient):
    """Graphiti's embedder interface over our EmbeddingsPort: one model per store set."""

    def __init__(self, port: EmbeddingsPort) -> None:
        self._port = port

    async def create(self, input_data: Any) -> list[float]:
        texts = [input_data] if isinstance(input_data, str) else [str(t) for t in input_data]
        return (await self._port.embed(texts))[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        return await self._port.embed(input_data_list)


def _at(day: date | None) -> datetime | None:
    return datetime(day.year, day.month, day.day, tzinfo=UTC) if day else None


def _day(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    to_native = getattr(value, "to_native", None)  # neo4j.time.DateTime
    return _day(to_native()) if to_native else None


def check_pair(subject: GraphEntity, edge: GraphEdge, obj: GraphEntity) -> None:
    try:
        allowed = RELATION_PAIRS[RelationType(edge.name)]
        pair = (EntityType(subject.entity_type), EntityType(obj.entity_type))
    except ValueError as exc:
        raise GraphWriteRefused(f"unknown relation or entity type: {exc}") from exc
    if pair not in allowed:
        raise GraphWriteRefused(f"{edge.name} does not allow {pair[0]} -> {pair[1]}")


class GraphitiGraph:
    component = "neo4j"

    def __init__(self, uri: str, user: str, password: str, embeddings: EmbeddingsPort) -> None:
        self._embedder = PortEmbedder(embeddings)
        self._g = Graphiti(
            uri,
            user,
            password,
            llm_client=NoModel(),
            embedder=self._embedder,
            cross_encoder=NoRerank(),
        )
        self._ready = False

    async def _setup(self) -> None:
        if not self._ready:
            await self._g.build_indices_and_constraints()
            self._ready = True

    # --- writes --------------------------------------------------------------------

    async def upsert_entity(self, entity: GraphEntity) -> None:
        await self._setup()
        node = EntityNode(
            uuid=entity.uuid,
            name=entity.name,
            group_id=entity.group_id,
            labels=[entity.entity_type],
            attributes=dict(entity.attributes),
        )
        await node.generate_name_embedding(self._embedder)
        await node.save(self._g.driver)

    async def add_triplet(self, subject: GraphEntity, edge: GraphEdge, obj: GraphEntity) -> str:
        check_pair(subject, edge, obj)
        await self._setup()
        for entity in (subject, obj):
            if not await self._exists(
                "MATCH (n:Entity {uuid: $uuid}) RETURN count(n)", entity.uuid
            ):
                await self.upsert_entity(entity)
        now = datetime.now(UTC)
        stored = EntityEdge(
            uuid=edge.uuid,
            group_id=edge.group_id,
            source_node_uuid=subject.uuid,
            target_node_uuid=obj.uuid,
            name=edge.name,
            fact=edge.fact,
            episodes=[],
            created_at=now,
            valid_at=_at(edge.valid_at),
            invalid_at=_at(edge.invalid_at),
            reference_time=_at(edge.valid_at) or now,
            attributes=dict(edge.attributes),
        )
        await stored.generate_embedding(self._embedder)
        await stored.save(self._g.driver)
        return edge.uuid

    async def invalidate_edge(self, edge_uuid: str, invalid_at: date) -> None:
        await self._setup()
        await self._g.driver.execute_query(
            "MATCH ()-[e:RELATES_TO {uuid: $uuid}]->() SET e.invalid_at = $at",
            uuid=edge_uuid,
            at=_at(invalid_at),
        )

    async def update_edge_attributes(self, edge_uuid: str, attributes: dict[str, Any]) -> None:
        await self._setup()
        clean = {k: v for k, v in attributes.items() if k not in _EDGE_FIELDS}
        await self._g.driver.execute_query(
            "MATCH ()-[e:RELATES_TO {uuid: $uuid}]->() SET e += $attributes",
            uuid=edge_uuid,
            attributes=clean,
        )

    async def _exists(self, cypher: str, uuid: str) -> bool:
        records, _, _ = await self._g.driver.execute_query(cypher, uuid=uuid)
        return bool(records and records[0][0])

    # --- reads ---------------------------------------------------------------------

    async def search_edges(
        self,
        group_id: str,
        relation_types: list[str],
        as_of: date | None = None,
        include_ended: bool = False,
        query: str | None = None,
        limit: int = 20,
    ) -> list[GraphEdgeHit]:
        await self._setup()
        if query:
            config = EDGE_HYBRID_SEARCH_RRF.model_copy(update={"limit": limit})
            edges = (
                await self._g.search_(
                    query,
                    config=config,
                    group_ids=[group_id],
                    search_filter=self._filters(relation_types, as_of, include_ended),
                )
            ).edges
        else:
            edges = await self._edges_by_cypher(
                group_id, relation_types, as_of, include_ended, limit
            )
        return await self._hits(edges)

    def _filters(self, types: list[str], as_of: date | None, include_ended: bool) -> SearchFilters:
        null = DateFilter(comparison_operator=ComparisonOperator.is_null)
        if as_of is not None:
            at = _at(as_of)
            return SearchFilters(
                edge_types=types or None,
                valid_at=[
                    [null],
                    [DateFilter(date=at, comparison_operator=ComparisonOperator.less_than_equal)],
                ],
                invalid_at=[
                    [null],
                    [DateFilter(date=at, comparison_operator=ComparisonOperator.greater_than)],
                ],
            )
        return SearchFilters(
            edge_types=types or None, invalid_at=None if include_ended else [[null]]
        )

    async def _edges_by_cypher(
        self, group_id: str, types: list[str], as_of: date | None, include_ended: bool, limit: int
    ) -> list[EntityEdge]:
        where = ["e.group_id = $group_id"]
        if types:
            where.append("e.name IN $types")
        if as_of is not None:
            where.append("(e.valid_at IS NULL OR e.valid_at <= $at)")
            where.append("(e.invalid_at IS NULL OR e.invalid_at > $at)")
        elif not include_ended:
            where.append("e.invalid_at IS NULL")
        records, _, _ = await self._g.driver.execute_query(
            "MATCH ()-[e:RELATES_TO]->() WHERE "
            + " AND ".join(where)
            + " RETURN e.uuid AS uuid ORDER BY e.valid_at DESC LIMIT $limit",
            group_id=group_id,
            types=types,
            at=_at(as_of),
            limit=limit,
        )
        uuids = [r["uuid"] for r in records]
        return await EntityEdge.get_by_uuids(self._g.driver, uuids) if uuids else []

    async def _hits(self, edges: list[EntityEdge]) -> list[GraphEdgeHit]:
        node_ids = list({u for e in edges for u in (e.source_node_uuid, e.target_node_uuid)})
        nodes = (
            {n.uuid: n for n in await EntityNode.get_by_uuids(self._g.driver, node_ids)}
            if node_ids
            else {}
        )
        return [
            GraphEdgeHit(
                edge=_edge(e),
                subject=_entity(nodes[e.source_node_uuid]),
                object=_entity(nodes[e.target_node_uuid]),
            )
            for e in edges
            if e.source_node_uuid in nodes and e.target_node_uuid in nodes
        ]

    async def neighbours(self, group_id: str, entity_uuid: str) -> list[GraphEdgeHit]:
        await self._setup()
        records, _, _ = await self._g.driver.execute_query(
            "MATCH (n:Entity {uuid: $uuid})-[e:RELATES_TO]-(:Entity) WHERE e.group_id = $group_id"
            " RETURN DISTINCT e.uuid AS uuid",
            uuid=entity_uuid,
            group_id=group_id,
        )
        uuids = [r["uuid"] for r in records]
        return await self._hits(
            await EntityEdge.get_by_uuids(self._g.driver, uuids) if uuids else []
        )

    async def export_subgraph(self, group_id: str) -> GraphExport:
        await self._setup()
        try:
            nodes = await EntityNode.get_by_group_ids(self._g.driver, [group_id])
        except GroupsNodesNotFoundError:
            nodes = []
        try:
            edges = await EntityEdge.get_by_group_ids(self._g.driver, [group_id])
        except GroupsEdgesNotFoundError:  # Graphiti raises for an empty group
            edges = []
        return GraphExport(entities=[_entity(n) for n in nodes], edges=await self._hits(edges))

    async def delete_group(self, group_id: str) -> None:
        await self._setup()
        await EntityNode.delete_by_group_id(self._g.driver, group_id)

    async def close(self) -> None:
        await self._g.close()  # type: ignore[no-untyped-call]


def _entity(node: EntityNode) -> GraphEntity:
    kind = next((label for label in node.labels if label != "Entity"), "Entity")
    attributes = {k: v for k, v in (node.attributes or {}).items() if k != "name_embedding"}
    return GraphEntity(
        uuid=node.uuid,
        group_id=node.group_id,
        entity_type=kind,
        name=node.name,
        attributes=attributes,
    )


def _edge(edge: EntityEdge) -> GraphEdge:
    attributes = {k: v for k, v in (edge.attributes or {}).items() if k not in _EDGE_FIELDS}
    return GraphEdge(
        uuid=edge.uuid,
        group_id=edge.group_id,
        name=edge.name,
        fact=edge.fact,
        valid_at=_day(edge.valid_at),
        invalid_at=_day(edge.invalid_at),
        attributes=attributes,
    )


def make(settings: Settings, embeddings: EmbeddingsPort | None = None) -> GraphitiGraph:
    if embeddings is None:
        raise ValueError("the graph adapter needs the embeddings adapter (one model per store set)")
    graph = settings.config.graph
    return GraphitiGraph(
        settings.secret(graph.uri_env),
        settings.secret(graph.user_env),
        settings.secret(graph.password_env),
        embeddings,
    )
