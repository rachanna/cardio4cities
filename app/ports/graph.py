from datetime import date
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class GraphEntity(BaseModel):
    model_config = ConfigDict(frozen=True)

    uuid: str  # uuid5(NAMESPACE, ent_…), LLD-1 §0
    group_id: str  # city_id
    entity_type: str
    name: str
    attributes: dict[str, Any]
    # Embedded by the workflow under its budget and limiter (BD-36); None: the adapter
    # embeds the name itself
    name_embedding: list[float] | None = None


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    uuid: str  # uuid5(NAMESPACE, claim_id), LLD-1 §6.3
    group_id: str
    name: str  # relation type
    fact: str
    valid_at: date | None
    invalid_at: date | None
    attributes: dict[str, Any]
    fact_embedding: list[float] | None = None  # as `GraphEntity.name_embedding`


class GraphEdgeHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    edge: GraphEdge
    subject: GraphEntity
    object: GraphEntity


class GraphExport(BaseModel):
    model_config = ConfigDict(frozen=True)

    entities: list[GraphEntity]
    edges: list[GraphEdgeHit]


class GraphPort(Protocol):
    async def upsert_entity(self, entity: GraphEntity) -> None: ...

    async def add_triplet(self, subject: GraphEntity, edge: GraphEdge, obj: GraphEntity) -> str: ...

    async def invalidate_edge(self, edge_uuid: str, invalid_at: date) -> None: ...

    async def update_edge_attributes(self, edge_uuid: str, attributes: dict[str, Any]) -> None:
        """Merge attributes into an edge, e.g. `status: contested` (LLD-1 §6.3, BD-11)."""
        ...

    async def search_edges(
        self,
        group_id: str,
        relation_types: list[str],
        as_of: date | None = None,
        include_ended: bool = False,
        query: str | None = None,
        limit: int = 20,
    ) -> list[GraphEdgeHit]: ...

    async def neighbours(self, group_id: str, entity_uuid: str) -> list[GraphEdgeHit]: ...

    async def export_subgraph(self, group_id: str) -> GraphExport: ...

    async def delete_group(self, group_id: str) -> None: ...

    # Embedding marker (R-82, BD-14): the graph stores entity and fact embeddings, so it
    # records which embedding model made them, and start-up refuses a different one.

    async def embedding_marker(self) -> str | None: ...

    async def set_embedding_marker(self, key: str) -> None: ...

    async def has_entities(self) -> bool: ...

    async def purge(self) -> int:
        """Delete everything in the graph; returns the number of nodes deleted."""
        ...
