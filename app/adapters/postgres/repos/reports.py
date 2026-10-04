"""Generated reports, one row per run and format (LLD-1 §4.5, LLD-4 §3.4)."""

import hashlib

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


class PostgresReportRepo:
    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def report(self, run_id: str, fmt: str) -> bytes | None:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT content FROM report WHERE run_id = :r AND format = :f"
                        " ORDER BY created_at DESC LIMIT 1"
                    ),
                    {"r": run_id, "f": fmt},
                )
            ).one_or_none()
        return bytes(row.content) if row else None

    async def add_report(
        self, report_id: str, city_id: str, run_id: str, fmt: str, content: bytes
    ) -> None:
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO report (report_id, city_id, run_id, format, content, sha256)"
                    " VALUES (:i, :c, :r, :f, :b, :h)"
                ),
                {
                    "i": report_id,
                    "c": city_id,
                    "r": run_id,
                    "f": fmt,
                    "b": content,
                    "h": hashlib.sha256(content).hexdigest(),
                },
            )
