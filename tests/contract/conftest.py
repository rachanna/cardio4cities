"""Database fixtures for tests marked `db`.

Uses TEST_DATABASE_URL (default: the compose Postgres, database c4c_test, created
if missing). Without a reachable server the tests skip locally; with
C4C_REQUIRE_DB=1 (CI) they fail instead.
"""

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from alembic import command
from alembic.config import Config

from app.adapters.postgres.db import SCHEMA
from app.adapters.postgres.relational import PostgresRelational

ROOT = Path(__file__).resolve().parents[2]
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://c4c:c4c@127.0.0.1:5432/c4c_test"
)


def _plain(url: str) -> str:
    scheme, rest = url.split("://", 1)
    return f"{scheme.split('+')[0]}://{rest}".replace("postgres://", "postgresql://", 1)


async def _ensure_database(url: str) -> None:
    parts = urlsplit(_plain(url))
    name = parts.path.lstrip("/")
    admin = await asyncpg.connect(urlunsplit(parts._replace(path="/postgres")), timeout=5)
    try:
        if not await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await admin.execute(f'CREATE DATABASE "{name}"')
    finally:
        await admin.close()


async def _drop_schema(url: str) -> None:
    conn = await asyncpg.connect(_plain(url), timeout=5)
    try:
        await conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
    finally:
        await conn.close()


def alembic_config(url: str) -> Config:
    return Config(toml_file=str(ROOT / "pyproject.toml"), attributes={"database_url": url})


@pytest.fixture(scope="session")
def database_url() -> str:
    try:
        asyncio.run(_ensure_database(TEST_DATABASE_URL))
    except (OSError, asyncpg.PostgresError, TimeoutError) as exc:
        message = f"test database unreachable ({type(exc).__name__}: {exc})"
        if os.environ.get("C4C_REQUIRE_DB") == "1":
            pytest.fail(message)
        pytest.skip(message + "; start it with `uv run poe up`")
    return TEST_DATABASE_URL


@pytest.fixture
def migrated(database_url: str) -> str:
    """A database with schema c4c rebuilt from the migrations."""
    asyncio.run(_drop_schema(database_url))
    command.upgrade(alembic_config(database_url), "head")
    return database_url


@pytest.fixture
async def relational(migrated: str) -> AsyncIterator[PostgresRelational]:
    store = PostgresRelational(migrated)
    yield store
    await store.close()
