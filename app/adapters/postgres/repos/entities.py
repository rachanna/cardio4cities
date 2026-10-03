"""EntityRepo on Postgres (LLD-1 §4.4, LLD-2 §6): one entity per (city, type, key)."""

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.models import Entity

_COLUMNS = "entity_id, city_id, entity_type, canonical_name, normalized_key, graph_uuid, attributes"


def _entity(row: dict[str, object]) -> Entity:
    return Entity.model_validate({**row, "graph_uuid": str(row["graph_uuid"])})


class PostgresEntityRepo:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def alias(self, city_id: str, surface_form: str) -> str | None:
        async with self._engine.connect() as conn:
            row = await conn.execute(
                text("SELECT entity_id FROM entity_alias WHERE city_id = :c AND surface_form = :s"),
                {"c": city_id, "s": surface_form},
            )
            return row.scalar_one_or_none()

    async def by_key(self, city_id: str, entity_type: str, normalized_key: str) -> str | None:
        async with self._engine.connect() as conn:
            row = await conn.execute(
                text(
                    "SELECT entity_id FROM entity WHERE city_id = :c AND entity_type = :t"
                    " AND normalized_key = :k"
                ),
                {"c": city_id, "t": entity_type, "k": normalized_key},
            )
            return row.scalar_one_or_none()

    async def add_entity(self, entity: Entity) -> str:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO entity (entity_id, city_id, entity_type, canonical_name,"
                    " normalized_key, graph_uuid, attributes) VALUES (:i, :c, :t, :n, :k, :g, :a)"
                    " ON CONFLICT (city_id, entity_type, normalized_key) DO NOTHING"
                ),
                {
                    "i": entity.entity_id,
                    "c": entity.city_id,
                    "t": entity.entity_type.value,
                    "n": entity.canonical_name,
                    "k": entity.normalized_key,
                    "g": entity.graph_uuid,
                    "a": json.dumps(entity.attributes),
                },
            )
            stored = await conn.execute(
                text(
                    "SELECT entity_id FROM entity WHERE city_id = :c AND entity_type = :t"
                    " AND normalized_key = :k"
                ),
                {"c": entity.city_id, "t": entity.entity_type.value, "k": entity.normalized_key},
            )
            return str(stored.scalar_one())

    async def add_alias(
        self, city_id: str, surface_form: str, entity_id: str, method: str, score: float | None
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO entity_alias (city_id, surface_form, entity_id, method, score)"
                    " VALUES (:c, :s, :e, :m, :x) ON CONFLICT (city_id, surface_form) DO NOTHING"
                ),
                {"c": city_id, "s": surface_form, "e": entity_id, "m": method, "x": score},
            )

    async def entities(self, city_id: str, entity_type: str) -> list[Entity]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    f"SELECT {_COLUMNS} FROM entity WHERE city_id = :c AND entity_type = :t"  # noqa: S608 - constant column list
                    " ORDER BY created_at"
                ),
                {"c": city_id, "t": entity_type},
            )
            return [_entity(dict(r)) for r in rows.mappings()]

    async def get(self, entity_ids: list[str]) -> dict[str, Entity]:
        if not entity_ids:
            return {}
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(f"SELECT {_COLUMNS} FROM entity WHERE entity_id = ANY(:ids)"),  # noqa: S608 - constant column list
                {"ids": entity_ids},
            )
            return {r["entity_id"]: _entity(dict(r)) for r in rows.mappings()}

    async def merge_attributes(self, entity_id: str, attributes: dict[str, object]) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE entity SET attributes = attributes || :a WHERE entity_id = :i"),
                {"a": json.dumps(attributes), "i": entity_id},
            )
