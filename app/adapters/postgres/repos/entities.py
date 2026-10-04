"""EntityRepo on Postgres (LLD-1 §4.4, LLD-2 §6): one entity per (city, type, key)."""

import json
from collections.abc import Callable
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.models import Entity

_COLUMNS = "entity_id, city_id, entity_type, canonical_name, normalized_key, graph_uuid, attributes"


_E_COLUMNS = ", ".join(f"e.{c.strip()}" for c in _COLUMNS.split(","))
_FACT_COUNTS = (
    f"SELECT {_E_COLUMNS}, count(*) AS facts FROM entity e JOIN relation r"  # noqa: S608 - constant column list
    " ON e.entity_id IN (r.subject_entity_id, r.object_entity_id)"
    " JOIN v_city_facts f ON f.claim_id = r.claim_id"
    " WHERE e.city_id = :c AND f.city_id = :c"
    " GROUP BY e.entity_id ORDER BY e.entity_type, count(*) DESC, e.canonical_name"
)


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

    async def match_names(
        self, city_id: str, texts: list[str], keys: list[str], min_similarity: float
    ) -> list[str]:
        """Entities a question names, by lookup only (LLD-5 §4.1, §4.3; nothing created):
        an alias written the same way, the same normalised key, or trigram similarity of
        at least `min_similarity` with the name or an alias."""
        if not texts:
            return []
        sql = (
            "SELECT DISTINCT e.entity_id FROM entity e"
            " LEFT JOIN entity_alias a ON a.entity_id = e.entity_id"
            " WHERE e.city_id = :c AND (e.normalized_key = ANY(:k) OR EXISTS ("
            "  SELECT 1 FROM unnest(CAST(:t AS text[])) t WHERE lower(a.surface_form) = lower(t)"
            "  OR similarity(e.canonical_name, t) >= :m"
            "  OR similarity(coalesce(a.surface_form, ''), t) >= :m))"
            " ORDER BY e.entity_id"
        )
        params = {"c": city_id, "t": texts, "k": keys, "m": min_similarity}
        async with self._engine.connect() as conn:
            rows = await conn.execute(text(sql), params)
            return [str(x) for x in rows.scalars()]

    async def names(self, city_id: str) -> list[tuple[str, str]]:
        """(entity_id, canonical name) of every entity of the city (acronym lookup)."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT entity_id, canonical_name FROM entity WHERE city_id = :c"),
                {"c": city_id},
            )
            return [(str(r.entity_id), str(r.canonical_name)) for r in rows]

    async def with_fact_counts(self, city_id: str) -> list[tuple[Entity, int]]:
        """Entities named by at least one fact of the city's latest run, with how many
        (D3-1): an entity only an unconfirmed claim named is not shown."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(text(_FACT_COUNTS), {"c": city_id})
            out = []
            for r in rows.mappings():
                row = dict(r)
                facts = int(row.pop("facts"))
                out.append((_entity(row), facts))
            return out

    async def get(self, entity_ids: list[str]) -> dict[str, Entity]:
        if not entity_ids:
            return {}
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(f"SELECT {_COLUMNS} FROM entity WHERE entity_id = ANY(:ids)"),  # noqa: S608 - constant column list
                {"ids": entity_ids},
            )
            return {r["entity_id"]: _entity(dict(r)) for r in rows.mappings()}

    async def update_attributes(
        self, entity_id: str, change: Callable[[dict[str, Any]], dict[str, Any] | None]
    ) -> dict[str, Any] | None:
        """Read the entity's attributes under a row lock, merge what `change` returns, and
        return the merged attributes (None when `change` keeps them). Concurrent updates
        of one entity apply one after the other (BD-19)."""
        async with self._engine.begin() as conn:
            current = (
                await conn.execute(
                    text("SELECT attributes FROM entity WHERE entity_id = :i FOR UPDATE"),
                    {"i": entity_id},
                )
            ).scalar_one()
            update = change(dict(current or {}))
            if update is None:
                return None
            await conn.execute(
                text("UPDATE entity SET attributes = attributes || :a WHERE entity_id = :i"),
                {"a": json.dumps(update), "i": entity_id},
            )
            return {**(current or {}), **update}

    async def merge_attributes(self, entity_id: str, attributes: dict[str, object]) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text("UPDATE entity SET attributes = attributes || :a WHERE entity_id = :i"),
                {"a": json.dumps(attributes), "i": entity_id},
            )
