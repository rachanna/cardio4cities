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


class GraphEdge(BaseModel):
    model_config = ConfigDict(frozen=True)

    uuid: str  # uuid5(NAMESPACE, claim_id), LLD-1 §6.3
    group_id: str
    name: str  # relation type
    fact: str
    valid_at: date | None
    invalid_at: date | None
    attributes: dict[str, Any]


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
