"""LangGraph's Postgres checkpointer in schema `lg` (LLD-1 §4, BD-14).

Tables are created by the saver's own setup call, inside schema `lg` (made by migration
0009), so they never mix with ours in `c4c`. Only the state's own types may be read back
from a checkpoint (an explicit allowlist, not LangGraph's permissive default).

psycopg's async mode needs a selector event loop. Windows' default Proactor loop cannot
run it: there the checkpointer reports itself unavailable and runs go on without
checkpoints (local development only; the deployment runs on Linux)."""

import asyncio
import sys
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.ports.checkpoint import CheckpointUnavailableError
from app.settings import Settings

SCHEMA = "lg"


def conninfo(url: str) -> str:
    """A libpq URL from DATABASE_URL (which may name a SQLAlchemy driver)."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        raise ValueError("DATABASE_URL must look like postgresql://user:password@host:port/db")
    return f"postgresql://{rest}" if scheme.startswith("postgres") else url


class PostgresCheckpointer:
    def __init__(self, database_url: str, allowed_types: list[type[Any]]) -> None:
        self._url = conninfo(database_url)
        self._allowed = allowed_types
        self._pool: AsyncConnectionPool[Any] | None = None
        self._saver: AsyncPostgresSaver | None = None
        self._lock = asyncio.Lock()

    async def saver(self) -> BaseCheckpointSaver[Any]:
        if sys.platform == "win32" and isinstance(
            asyncio.get_running_loop(), asyncio.ProactorEventLoop
        ):
            raise CheckpointUnavailableError(
                "psycopg async needs a selector event loop; Windows' Proactor loop is running"
            )
        async with self._lock:
            if self._saver is None:
                pool: AsyncConnectionPool[Any] = AsyncConnectionPool(
                    self._url,
                    open=False,
                    kwargs={
                        "autocommit": True,
                        "prepare_threshold": 0,
                        "row_factory": dict_row,
                        "options": f"-c search_path={SCHEMA}",
                    },
                )
                await pool.open()
                saver = AsyncPostgresSaver(
                    pool,
                    serde=JsonPlusSerializer(allowed_msgpack_modules=self._allowed),
                )
                await saver.setup()
                self._pool, self._saver = pool, saver
            return self._saver

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = self._saver = None


def make(settings: Settings, allowed_types: list[type[Any]] | None = None) -> PostgresCheckpointer:
    return PostgresCheckpointer(
        settings.secret(settings.config.relational.dsn_env), allowed_types or []
    )
