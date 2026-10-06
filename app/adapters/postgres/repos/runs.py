"""Cities, runs and run events (LLD-1 §4.2, LLD-2 §10)."""

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from app.domain.models import CityIdentity
from app.domain.place_names import real_alternate_names


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

    async def city_row(self, city_id: str) -> dict[str, Any] | None:
        """The city with its latest run (D3-1): None for an unknown city."""
        async with self._engine.connect() as conn:
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT c.city_id, c.gazetteer_id, c.identity, c.latest_run_id,"
                            " r.status AS latest_run_status, r.started_at AS latest_run_started,"
                            " r.finished_at AS latest_run_at FROM city c"
                            " LEFT JOIN run r ON r.run_id = c.latest_run_id WHERE c.city_id = :c"
                        ),
                        {"c": city_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return dict(row) if row else None

    async def cities(self, limit: int, offset: int) -> list[dict[str, Any]]:
        """Cities with a finished run, newest first ("Open existing", AT-25, AT-37)."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT c.city_id, c.identity->>'name' AS name,"
                    " c.identity->>'country_name' AS country_name, c.latest_run_id,"
                    " coalesce(r.finished_at, r.started_at) AS latest_run_at,"
                    " r.status AS latest_run_status FROM city c"
                    " JOIN run r ON r.run_id = c.latest_run_id"
                    " ORDER BY latest_run_at DESC NULLS LAST, c.city_id LIMIT :l OFFSET :o"
                ),
                {"l": limit, "o": offset},
            )
            return [dict(r) for r in rows.mappings()]

    async def city_identity(self, city_id: str) -> CityIdentity:
        """The stored identity, with the gazetteer's real alternate names read now, so
        cities created before BD-51 have them too."""
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT c.identity, p.alternate_names FROM city c"
                        " LEFT JOIN ref_place p ON p.gazetteer_id = c.gazetteer_id"
                        " WHERE c.city_id = :c"
                    ),
                    {"c": city_id},
                )
            ).one()
        identity = dict(row.identity)
        identity["alternate_names"] = real_alternate_names(
            list(row.alternate_names or []), identity["name"], identity["ascii_name"]
        )
        return CityIdentity.model_validate(identity)

    async def create_run(
        self,
        run_id: str,
        city_id: str,
        budget: dict[str, Any],
        versions: dict[str, str],
        owner: str | None = None,
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO run (run_id, city_id, status, budget, versions, owner,"
                    " heartbeat_at) VALUES (:r, :c, 'queued', :b, :v, :o,"
                    " CASE WHEN CAST(:o AS text) IS NULL THEN NULL ELSE now() END)"
                ),
                {
                    "r": run_id,
                    "c": city_id,
                    "b": json.dumps(budget),
                    "v": json.dumps(versions),
                    "o": owner,
                },
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
            # Under the run's row lock: an event already stored is returned, not repeated
            existing = (
                await conn.execute(
                    text("SELECT seq FROM run_event WHERE event_id = :e"), {"e": event_id}
                )
            ).scalar_one_or_none()
            if existing is not None:
                return int(existing)
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

    # --- coverage and resume (D2-5, LLD-2 §11, BD-14) ----------------------------------

    async def save_slot_result(self, run_id: str, result: dict[str, Any]) -> None:
        """One row per slot per run; a re-plan round replaces the earlier round's row."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO slot_result (run_id, slot_id, status, flags, replans_used,"
                    " queries_tried, sources_checked, best_claim_ids, gap_note)"
                    " VALUES (:r, :slot_id, :status, :flags, :replans_used, :queries_tried,"
                    " :sources_checked, :best_claim_ids, :gap_note)"
                    " ON CONFLICT (run_id, slot_id) DO UPDATE SET status = EXCLUDED.status,"
                    " flags = EXCLUDED.flags, replans_used = EXCLUDED.replans_used,"
                    " queries_tried = EXCLUDED.queries_tried,"
                    " sources_checked = EXCLUDED.sources_checked,"
                    " best_claim_ids = EXCLUDED.best_claim_ids, gap_note = EXCLUDED.gap_note"
                ),
                {"r": run_id, **result},
            )

    async def slot_results(self, run_id: str) -> list[dict[str, Any]]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT * FROM slot_result WHERE run_id = :r ORDER BY slot_id"),
                {"r": run_id},
            )
            return [dict(r) for r in rows.mappings()]

    async def save_budget_used(self, run_id: str, used: dict[str, Any]) -> None:
        """The ledger's counters, kept with the run's limits so a resume can restore them."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE run SET budget = budget"
                    " || jsonb_build_object('used', CAST(:u AS jsonb)) WHERE run_id = :r"
                ),
                {"u": json.dumps(used, default=str), "r": run_id},
            )

    async def stranded_runs(self) -> list[dict[str, Any]]:
        """Runs left `running` (or `queued`) by a process that stopped."""
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text(
                    "SELECT run_id, city_id, status, resume_attempts, budget, owner,"
                    " extract(epoch FROM now() - heartbeat_at) AS quiet_s FROM run"
                    " WHERE status IN ('queued', 'running') ORDER BY run_id"
                )
            )
            return [dict(r) for r in rows.mappings()]

    async def heartbeat(self, owner: str) -> None:
        """The owner's active runs are alive (BD-25)."""
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "UPDATE run SET heartbeat_at = now()"
                    " WHERE owner = :o AND status IN ('queued', 'running')"
                ),
                {"o": owner},
            )

    async def claim_stale(self, run_id: str, owner: str, stale_after_s: float) -> bool:
        """Take over a stranded run whose owner has gone quiet, counting the resume. One
        atomic update: two processes can never both take it (BD-25)."""
        async with self._engine.begin() as conn:
            row = (
                await conn.execute(
                    text(
                        "UPDATE run SET owner = :o, heartbeat_at = now(),"
                        " resume_attempts = resume_attempts + 1"
                        " WHERE run_id = :r AND status IN ('queued', 'running')"
                        " AND (heartbeat_at IS NULL"
                        "      OR heartbeat_at < now() - make_interval(secs => :s))"
                        " RETURNING run_id"
                    ),
                    {"o": owner, "r": run_id, "s": stale_after_s},
                )
            ).first()
            return row is not None
