"""Engine creation. Everything lives in schema `c4c`; `pg_trgm` lives in `public` (LLD-1 §4)."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

SCHEMA = "c4c"
SEARCH_PATH = f"{SCHEMA}, public"


def async_dsn(url: str) -> str:
    """Accept `postgres://`, `postgresql://` or an explicit driver; return an asyncpg URL."""
    scheme, sep, rest = url.partition("://")
    if not sep:
        raise ValueError("DATABASE_URL must look like postgresql://user:password@host:port/db")
    if scheme in ("postgres", "postgresql"):
        scheme = "postgresql+asyncpg"
    elif not scheme.startswith("postgresql+"):
        raise ValueError(f"DATABASE_URL scheme {scheme!r} is not PostgreSQL")
    return f"{scheme}://{rest}"


def create_engine(url: str) -> AsyncEngine:
    return create_async_engine(
        async_dsn(url),
        pool_pre_ping=True,
        connect_args={"server_settings": {"search_path": SEARCH_PATH}},
    )


def split_sql(script: str) -> list[str]:
    """Split a migration script into statements; asyncpg runs one statement per call."""
    return [stmt.strip() for stmt in script.split(";\n") if stmt.strip().rstrip(";")]
