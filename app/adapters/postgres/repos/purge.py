"""Removing one city from Postgres (LLD-1 §8, BD-36, BD-42): its runs and everything they
wrote, its answers and reports, and the LangGraph checkpoints of its runs (schema `lg`).
One transaction, children before parents. Used only by `scripts/purge_city.py`; no
workflow or API code deletes anything."""

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

# (table, rows of the city): children first, so every foreign key is satisfied
_CLAIMS = "claim_id IN (SELECT claim_id FROM claim WHERE city_id = :c)"
_RUNS = "run_id IN (SELECT run_id FROM run WHERE city_id = :c)"
_SOURCES = f"source_id IN (SELECT source_id FROM source WHERE {_RUNS})"  # noqa: S608
STEPS: tuple[tuple[str, str], ...] = (
    ("answer", "city_id = :c"),
    ("report", "city_id = :c"),
    ("graph_link", _CLAIMS),
    ("relation", _CLAIMS),
    ("verdict", _CLAIMS),
    ("consistency", _CLAIMS),
    (
        "contested_pair",
        "claim_a IN (SELECT claim_id FROM claim WHERE city_id = :c)"
        " OR claim_b IN (SELECT claim_id FROM claim WHERE city_id = :c)"
        " OR headline_claim IN (SELECT claim_id FROM claim WHERE city_id = :c)",
    ),
    ("statistic", _CLAIMS),
    ("entity_alias", "city_id = :c"),
    ("entity", "city_id = :c"),
    ("claim", "city_id = :c"),
    ("snapshot", _SOURCES),
    ("source", _RUNS),
    ("crawl_decision", _RUNS),
    ("search_query", _RUNS),
    ("slot_result", _RUNS),
    ("run_summary", _RUNS),
    ("run_seq", _RUNS),
    ("run_event", _RUNS),
)
CHECKPOINT_TABLES = ("checkpoint_writes", "checkpoint_blobs", "checkpoints")


@dataclass(frozen=True)
class CityRow:
    city_id: str
    name: str
    country: str
    runs: int
    active_runs: int  # queued or running: never purged


class PostgresPurgeRepo:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def cities(self) -> list[CityRow]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT c.city_id, c.identity->>'name' AS name,"
                    " c.identity->>'country_name' AS country, count(r.run_id) AS runs,"
                    " count(r.run_id) FILTER (WHERE r.status IN ('queued','running')) AS active"
                    " FROM city c LEFT JOIN run r USING (city_id)"
                    " GROUP BY c.city_id ORDER BY c.created_at"
                )
            )
            return [
                CityRow(r.city_id, r.name or "", r.country or "", r.runs, r.active) for r in rows
            ]

    async def city(self, city_id: str) -> CityRow | None:
        return next((c for c in await self.cities() if c.city_id == city_id), None)

    async def counts(self, city_id: str) -> dict[str, int]:
        """What a purge would delete, by table (the dry run)."""
        out: dict[str, int] = {}
        async with self._engine.connect() as conn:
            for table, where in STEPS:
                sql = f"SELECT count(*) FROM {table} WHERE {where}"  # noqa: S608 - module constants
                out[table] = (await conn.execute(text(sql), {"c": city_id})).scalar_one()
            out["run"] = (
                await conn.execute(
                    text("SELECT count(*) FROM run WHERE city_id = :c"), {"c": city_id}
                )
            ).scalar_one()
        return out

    async def purge(self, city_id: str) -> dict[str, int]:
        """Delete the city and everything of it. Returns rows deleted by table."""
        deleted: dict[str, int] = {}
        async with self._engine.begin() as conn:
            run_ids = list(
                (
                    await conn.execute(
                        text("SELECT run_id FROM run WHERE city_id = :c"), {"c": city_id}
                    )
                ).scalars()
            )
            await conn.execute(
                text("UPDATE city SET latest_run_id = NULL WHERE city_id = :c"), {"c": city_id}
            )
            for table, where in STEPS:
                sql = f"DELETE FROM {table} WHERE {where}"  # noqa: S608 - module constants
                deleted[table] = (await conn.execute(text(sql), {"c": city_id})).rowcount
            deleted["run"] = (
                await conn.execute(text("DELETE FROM run WHERE city_id = :c"), {"c": city_id})
            ).rowcount
            deleted["city"] = (
                await conn.execute(text("DELETE FROM city WHERE city_id = :c"), {"c": city_id})
            ).rowcount
            # Checkpoints hold the runs' state, search snippets included (BD-36)
            for table in CHECKPOINT_TABLES:
                exists = await conn.execute(text("SELECT to_regclass(:t)"), {"t": f"lg.{table}"})
                if exists.scalar_one() is None or not run_ids:
                    continue
                sql = f"DELETE FROM lg.{table} WHERE thread_id = ANY(:ids)"  # noqa: S608
                deleted[f"lg.{table}"] = (await conn.execute(text(sql), {"ids": run_ids})).rowcount
        return deleted
