"""Alembic environment. Needs only DATABASE_URL (or `database_url` in config attributes).

Creates schema `c4c` and keeps Alembic's version table there. Runs on asyncpg.
"""

import asyncio
import logging
import os

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.engine import Connection

from app.adapters.postgres.db import SCHEMA, SEARCH_PATH, create_engine

if not logging.getLogger().handlers:
    logging.basicConfig(format="%(message)s")
logging.getLogger("alembic.runtime.migration").setLevel(logging.INFO)


def _database_url() -> str:
    url: str = context.config.attributes.get("database_url") or ""
    if not url:  # command line: .env never overrides the real environment
        load_dotenv(".env", override=False)
        url = os.environ.get("DATABASE_URL", "")
    if not url.strip():
        raise SystemExit("DATABASE_URL is not set; it is the only setting migrations need")
    return url


def _run(connection: Connection) -> None:
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    connection.execute(text(f"SET search_path TO {SEARCH_PATH}"))
    context.configure(connection=connection, version_table_schema=SCHEMA, transactional_ddl=True)
    with context.begin_transaction():
        context.run_migrations()


async def _main() -> None:
    engine = create_engine(_database_url())
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_run)
            await connection.commit()
    finally:
        await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("offline (--sql) mode is not supported; run against a database")
asyncio.run(_main())
