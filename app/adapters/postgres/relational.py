"""RelationalPort over Postgres: one engine shared by the repositories."""

from sqlalchemy import text

from app.adapters.postgres.db import create_engine
from app.adapters.postgres.repos.answers import PostgresAnswerRepo
from app.adapters.postgres.repos.entities import PostgresEntityRepo
from app.adapters.postgres.repos.purge import PostgresPurgeRepo
from app.adapters.postgres.repos.reference import PostgresReferenceRepo
from app.adapters.postgres.repos.reports import PostgresReportRepo
from app.adapters.postgres.repos.research import PostgresResearchRepo
from app.adapters.postgres.repos.runs import PostgresRunRepo
from app.adapters.postgres.repos.sources import PostgresSourceRepo
from app.settings import Settings


class PostgresRelational:
    def __init__(self, database_url: str) -> None:
        self._engine = create_engine(database_url)
        self._reference = PostgresReferenceRepo(self._engine)
        self._sources = PostgresSourceRepo(self._engine)
        self._runs = PostgresRunRepo(self._engine)
        self._research = PostgresResearchRepo(self._engine)
        self._entities = PostgresEntityRepo(self._engine)
        self._answers = PostgresAnswerRepo(self._engine)
        self._reports = PostgresReportRepo(self._engine)
        self._purge = PostgresPurgeRepo(self._engine)

    @property
    def reference(self) -> PostgresReferenceRepo:
        return self._reference

    @property
    def sources(self) -> PostgresSourceRepo:
        return self._sources

    @property
    def entities(self) -> PostgresEntityRepo:
        return self._entities

    @property
    def runs(self) -> PostgresRunRepo:
        return self._runs

    @property
    def research(self) -> PostgresResearchRepo:
        return self._research

    @property
    def answers(self) -> PostgresAnswerRepo:
        return self._answers

    @property
    def reports(self) -> PostgresReportRepo:
        return self._reports

    @property
    def purge(self) -> PostgresPurgeRepo:
        """Removing a city (`scripts/purge_city.py` only; not on the port)."""
        return self._purge

    async def ping(self) -> None:
        async with self._engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def close(self) -> None:
        await self._engine.dispose()


def make(settings: Settings) -> PostgresRelational:
    return PostgresRelational(settings.secret(settings.config.relational.dsn_env))
