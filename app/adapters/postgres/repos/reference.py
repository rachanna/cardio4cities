"""Reference data (LLD-1 §3, §4.1): reads for start-up checks, idempotent syncs for loaders.

A sync stages rows with COPY, upserts only rows that differ, and deletes rows no
longer in the input unless something refers to them. Running a sync twice with
the same input changes nothing; the second `SyncResult` shows zero changes.
"""

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.adapters.postgres.db import SCHEMA
from app.domain.models import IndicatorDef, SlotDef


@dataclass(frozen=True)
class SyncResult:
    table: str
    inserted: int
    updated: int
    deleted: int
    total: int

    def __str__(self) -> str:
        return (
            f"{self.table}: {self.total} rows ({self.inserted} inserted, "
            f"{self.updated} updated, {self.deleted} deleted)"
        )


@dataclass(frozen=True)
class SourceEntry:
    provider: str
    adapter: str
    config: dict[str, Any]  # geography, representativeness, indicators…


@dataclass(frozen=True)
class _Table:
    name: str
    keys: tuple[str, ...]
    columns: tuple[str, ...]
    delete_guard: str = ""  # extra condition protecting referenced rows from deletion


_COUNTRY = _Table(
    "ref_country",
    ("iso2",),
    ("iso2", "iso3", "name", "languages"),
    f"AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.ref_place p WHERE p.country_iso2 = t.iso2)"
    f" AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.ref_admin1 a WHERE a.country_iso2 = t.iso2)",
)
_ADMIN1 = _Table(
    "ref_admin1", ("country_iso2", "admin1_code"), ("country_iso2", "admin1_code", "name")
)
_PLACE = _Table(
    "ref_place",
    ("gazetteer_id",),
    (
        "gazetteer_id",
        "name",
        "ascii_name",
        "alternate_names",
        "country_iso2",
        "admin1_code",
        "admin2_code",
        "population",
        "lat",
        "lon",
        "timezone",
    ),
    f"AND NOT EXISTS (SELECT 1 FROM {SCHEMA}.city c WHERE c.gazetteer_id = t.gazetteer_id)",
)
_SLOT = _Table(
    "ref_slot",
    ("slot_id",),
    (
        "slot_id",
        "dimension",
        "question",
        "short_label",
        "answer_kind",
        "indicator_codes",
        "relation_types",
        "headline",
        "accepted_levels",
    ),
)
_INDICATOR = _Table("ref_indicator", ("code",), ("code", "name", "comparability_key", "notes"))
_SOURCE = _Table("ref_source", ("provider",), ("provider", "adapter", "config"))


class PostgresReferenceRepo:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    # --- reads (ReferenceRepo port) ---------------------------------------

    async def slot_ids(self) -> list[str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(text("SELECT slot_id FROM ref_slot ORDER BY slot_id"))
            return [row.slot_id for row in rows]

    async def indicator_codes(self) -> dict[str, str]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(text("SELECT provider, config FROM ref_source"))
            return {
                f"{row.provider}.{indicator}": str(spec.get("code", ""))
                for row in rows
                for indicator, spec in row.config.get("indicators", {}).items()
            }

    async def slots(self) -> list[SlotDef]:
        async with self._engine.connect() as conn:
            rows = (await conn.execute(text("SELECT * FROM ref_slot ORDER BY slot_id"))).mappings()
            return [SlotDef.model_validate(dict(r)) for r in rows]

    async def indicators(self) -> list[IndicatorDef]:
        async with self._engine.connect() as conn:
            rows = (
                await conn.execute(text("SELECT * FROM ref_indicator ORDER BY code"))
            ).mappings()
            return [IndicatorDef.model_validate(dict(r)) for r in rows]

    async def search_places(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Trigram similarity on name and alternate names, then population (LLD-4 §3.2)."""
        sql = text(
            "SELECT p.gazetteer_id, p.name, p.country_iso2, c.name AS country_name,"
            " a.name AS admin1_name, p.population,"
            " greatest(similarity(p.ascii_name, :q), similarity(p.name, :q),"
            "   CASE WHEN :q = ANY(p.alternate_names) THEN 1.0 ELSE 0 END) AS score"
            " FROM ref_place p JOIN ref_country c ON c.iso2 = p.country_iso2"
            " LEFT JOIN ref_admin1 a ON a.country_iso2 = p.country_iso2"
            "   AND a.admin1_code = p.admin1_code"
            " WHERE similarity(p.ascii_name, :q) > 0.3 OR similarity(p.name, :q) > 0.3"
            "   OR :q = ANY(p.alternate_names)"
            " ORDER BY score DESC, p.population DESC NULLS LAST LIMIT :limit"
        )
        async with self._engine.connect() as conn:
            rows = (await conn.execute(sql, {"q": query.strip(), "limit": limit})).mappings()
            return [dict(r) for r in rows]

    async def place_identity(self, gazetteer_id: str) -> dict[str, Any] | None:
        """Gazetteer fields for CityIdentity (LLD-1 §2.1); the caller adds city_id."""
        sql = text(
            "SELECT p.gazetteer_id, p.name, p.ascii_name, p.country_iso2, c.iso3 AS country_iso3,"
            " c.name AS country_name, p.admin1_code, a.name AS admin1_name, p.population,"
            " p.lat, p.lon, c.languages FROM ref_place p"
            " JOIN ref_country c ON c.iso2 = p.country_iso2"
            " LEFT JOIN ref_admin1 a ON a.country_iso2 = p.country_iso2"
            "   AND a.admin1_code = p.admin1_code WHERE p.gazetteer_id = :g"
        )
        async with self._engine.connect() as conn:
            row = (await conn.execute(sql, {"g": gazetteer_id})).mappings().one_or_none()
        return dict(row) if row else None

    # --- syncs (loaders only) ---------------------------------------------

    async def sync_slots(self, slots: Sequence[SlotDef]) -> SyncResult:
        records = [
            (
                s.slot_id,
                s.dimension,
                s.question,
                s.short_label,
                s.answer_kind.value,
                list(s.indicator_codes),
                [r.value for r in s.relation_types],
                s.headline,
                [level.value for level in s.accepted_levels],
            )
            for s in slots
        ]
        return (await self._sync([(_SLOT, records)]))[0]

    async def sync_indicators(self, indicators: Sequence[IndicatorDef]) -> SyncResult:
        records = [(i.code, i.name, i.comparability_key, i.notes) for i in indicators]
        return (await self._sync([(_INDICATOR, records)]))[0]

    async def sync_sources(self, sources: Sequence[SourceEntry]) -> SyncResult:
        records = [(s.provider, s.adapter, json.dumps(s.config, sort_keys=True)) for s in sources]
        return (await self._sync([(_SOURCE, records)]))[0]

    async def sync_gazetteer(
        self,
        countries: Sequence[tuple[Any, ...]],
        admin1: Sequence[tuple[Any, ...]],
        places: Sequence[tuple[Any, ...]],
    ) -> list[SyncResult]:
        """Rows in the column order of ref_country, ref_admin1 and ref_place."""
        return await self._sync([(_COUNTRY, countries), (_ADMIN1, admin1), (_PLACE, places)])

    async def _sync(
        self, batches: list[tuple[_Table, Sequence[tuple[Any, ...]]]]
    ) -> list[SyncResult]:
        """Upsert batches in order, then delete missing rows in reverse (FK-safe), atomically."""
        async with self._engine.begin() as conn:
            raw = await conn.get_raw_connection()
            pg: Any = raw.driver_connection  # asyncpg.Connection
            stages: list[str] = []
            upserts: list[tuple[int, int]] = []
            for table, records in batches:
                stage = f"stage_{table.name}_{uuid.uuid4().hex[:8]}"
                stages.append(stage)
                cols = ", ".join(table.columns)
                await pg.execute(
                    f"CREATE TEMP TABLE {stage} AS SELECT {cols} FROM {SCHEMA}.{table.name} "
                    f"WITH NO DATA"
                )
                await pg.copy_records_to_table(stage, records=records, columns=list(table.columns))
                updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in table.columns)
                target = ", ".join(f"t.{c}" for c in table.columns)
                excluded = ", ".join(f"EXCLUDED.{c}" for c in table.columns)
                rows = await pg.fetch(
                    f"INSERT INTO {SCHEMA}.{table.name} AS t ({cols}) SELECT {cols} FROM {stage} "
                    f"ON CONFLICT ({', '.join(table.keys)}) DO UPDATE SET {updates} "
                    f"WHERE ({target}) IS DISTINCT FROM ({excluded}) "
                    f"RETURNING (xmax = 0) AS inserted"
                )
                inserted = sum(1 for r in rows if r["inserted"])
                upserts.append((inserted, len(rows) - inserted))

            results: list[SyncResult] = []
            for (table, _), stage, (inserted, updated) in reversed(
                list(zip(batches, stages, upserts, strict=True))
            ):
                match = " AND ".join(f"s.{k} = t.{k}" for k in table.keys)
                status = await pg.execute(
                    f"DELETE FROM {SCHEMA}.{table.name} t "
                    f"WHERE NOT EXISTS (SELECT 1 FROM {stage} s WHERE {match}) {table.delete_guard}"
                )
                total = await pg.fetchval(f"SELECT count(*) FROM {SCHEMA}.{table.name}")
                await pg.execute(f"DROP TABLE {stage}")
                results.append(
                    SyncResult(table.name, inserted, updated, int(status.split()[-1]), total)
                )
            return list(reversed(results))
