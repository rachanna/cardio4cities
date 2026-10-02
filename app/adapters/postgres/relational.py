"""RelationalPort over Postgres: one engine shared by the repositories."""

from sqlalchemy import text

from app.adapters.postgres.db import create_engine
from app.adapters.postgres.repos.reference import PostgresReferenceRepo
from app.settings import Settings


class PostgresRelational:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)
        self._reference = PostgresReferenceRepo(self._engine)

    @property
    def reference(self) -> PostgresReferenceRepo:
        return self._reference

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self._engine.dispose()


def make(settings: Settings) -> PostgresRelational:
    return PostgresRelational(settings.secret(settings.config.relational.dsn_env))
