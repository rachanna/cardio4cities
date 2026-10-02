"""Neo4j health probe: `RETURN 1` (LLD-4 §7)."""

from neo4j import AsyncGraphDatabase

from app.settings import Settings


class Neo4jProbe:
    component = "neo4j"

    def __init__(self, uri: str, user: str, password: str, timeout_s: float = 3.0) -> None:
        self._driver = AsyncGraphDatabase.driver(
            uri, auth=(user, password), connection_timeout=timeout_s
        )

    async def check(self) -> None:
        # One attempt: execute_query would retry for up to 30 s, which a health check must not.
        async with self._driver.session() as session:
            record = await (await session.run("RETURN 1 AS ok")).single()
        if record is None or record["ok"] != 1:
            raise RuntimeError("unexpected Neo4j reply")

    async def close(self) -> None:
        await self._driver.close()


def make(settings: Settings) -> Neo4jProbe:
    graph = settings.config.graph
    return Neo4jProbe(
        settings.secret(graph.uri_env),
        settings.secret(graph.user_env),
        settings.secret(graph.password_env),
    )
