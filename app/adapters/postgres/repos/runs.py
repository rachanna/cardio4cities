"""Cities, runs and run events (LLD-1 §4.2, LLD-2 §10)."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.models import CityIdentity


class PostgresRunRepo:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def city_for_place(self, gazetteer_id: str) -> str | None:
        async with self._engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT city_id FROM city WHERE gazetteer_id = :g"), {"g": gazetteer_id}
                )
            ).scalar_one_or_none()

    async def create_city(self, identity: CityIdentity) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO city (city_id, gazetteer_id, identity) VALUES (:c, :g, :i)"
                    " ON CONFLICT (gazetteer_id) DO NOTHING"
                ),
                {
                    "c": identity.city_id,
                    "g": identity.gazetteer_id,
                    "i": identity.model_dump_json(),
                },
            )

    async def city_identity(self, city_id: str) -> CityIdentity:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text("SELECT identity FROM city WHERE city_id = :c"), {"c": city_id}
                )
            ).one()
        return CityIdentity.model_validate(row.identity)

    async def create_run(
        self, run_id: str, city_id: str, budget: dict[str, Any], versions: dict[str, str]
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO run (run_id, city_id, status, budget, versions)"
                    " VALUES (:r, :c, 'queued', :b, :v)"
                ),
                {"r": run_id, "c": city_id, "b": json.dumps(budget), "v": json.dumps(versions)},
            )
            await conn.execute(text("INSERT INTO run_seq (run_id) VALUES (:r)"), {"r": run_id})

    async def active_run(self) -> str | None:
        async with self._engine.connect() as conn:
            return (
                await conn.execute(
                    text("SELECT run_id FROM run WHERE status IN ('queued', 'running') LIMIT 1")
                )
            ).scalar_one_or_none()

    async def runs_today(self) -> int:
        async with self._engine.connect() as conn:
            return int(
                (
                    await conn.execute(
                        text(
                            "SELECT count(*) FROM run WHERE started_at >= date_trunc('day', now())"
                        )
                    )
                ).scalar_one()
            )

    async def set_status(self, run_id: str, status: str, error: str | None = None) -> None:
        now = datetime.now(UTC)
        started = "UPDATE run SET status = :s, error = :e, started_at = :t WHERE run_id = :r"
        finished = "UPDATE run SET status = :s, error = :e, finished_at = :t WHERE run_id = :r"
        async with self._engine.begin() as conn:
            await conn.execute(
                text(started if status == "running" else finished),
                {"s": status, "e": error, "t": now, "r": run_id},
            )
            if status in ("completed", "stopped_by_budget"):
                await conn.execute(
                    text(
                        "UPDATE city SET latest_run_id = :r"
                        " WHERE city_id = (SELECT city_id FROM run WHERE run_id = :r)"
                    ),
                    {"r": run_id},
                )

    async def run_row(self, run_id: str) -> dict[str, Any] | None:
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT r.*, s.summary FROM run r"
                            " LEFT JOIN run_summary s ON s.run_id = r.run_id WHERE r.run_id = :r"
                        ),
                        {"r": run_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    async def save_summary(self, run_id: str, summary: dict[str, Any]) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO run_summary (run_id, summary) VALUES (:r, :s)"
                    " ON CONFLICT (run_id) DO UPDATE SET summary = EXCLUDED.summary"
                ),
                {"r": run_id, "s": json.dumps(summary, default=str)},
            )

    # --- events (LLD-2 §10.1) -------------------------------------------------------

    async def append_event(
        self, run_id: str, event_id: str, type_: str, payload: dict[str, Any]
    ) -> int:
        """Numbered in the same transaction under a row lock, so seq is gap-free per run."""
        async with self._engine.begin() as conn:
            seq = int(
                (
                    await conn.execute(
                        text("SELECT next_seq FROM run_seq WHERE run_id = :r FOR UPDATE"),
                        {"r": run_id},
                    )
                ).scalar_one()
            )
            await conn.execute(
                text(
                    "INSERT INTO run_event (run_id, seq, event_id, type, payload)"
                    " VALUES (:r, :s, :e, :t, :p)"
                ),
                {
                    "r": run_id,
                    "s": seq,
                    "e": event_id,
                    "t": type_,
                    "p": json.dumps(payload, default=str),
                },
            )
            await conn.execute(
                text("UPDATE run_seq SET next_seq = next_seq + 1 WHERE run_id = :r"), {"r": run_id}
            )
        return seq

    async def events_after(
        self, run_id: str, after_seq: int, limit: int = 500
    ) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT seq, type, payload FROM run_event WHERE run_id = :r AND seq > :s"
                    " ORDER BY seq LIMIT :l"
                ),
                {"r": run_id, "s": after_seq, "l": limit},
            )
            return [{"seq": r.seq, "type": r.type, "payload": r.payload} for r in rows]
