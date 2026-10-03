"""`poe purge-graph`: delete everything in the local Neo4j graph, the embedding marker too
(R-82, BD-14). Start-up refuses a graph whose embeddings came from another model; this is
the fix for a local database. Refuses to run when APP_ENV is `deployed`.

Postgres and Qdrant are untouched: claims and facts stay, and `brief_ready` writes a
fact's edge again on the next run of its city."""

import asyncio
import os
import sys

from dotenv import load_dotenv

from app.adapters.graph.graphiti import GraphitiGraph
from app.settings import load_settings


class _NoEmbeddings:
    """Purging embeds nothing."""

    dimension = 0
    key = "none"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("purge-graph embeds nothing")


async def purge() -> int:
    settings = load_settings()
    graph_cfg = settings.config.graph
    graph = GraphitiGraph(
        settings.secret(graph_cfg.uri_env),
        settings.secret(graph_cfg.user_env),
        settings.secret(graph_cfg.password_env),
        _NoEmbeddings(),
    )
    try:
        return await graph.purge()
    finally:
        await graph.close()


def main() -> int:
    load_dotenv(".env", override=False)
    if os.environ.get("APP_ENV", "local") == "deployed":
        print("purge-graph refuses to run with APP_ENV=deployed", file=sys.stderr)
        return 2
    deleted = asyncio.run(purge())
    print(f"graph purged: {deleted} nodes deleted; the next start-up writes a new marker")
    return 0


if __name__ == "__main__":
    sys.exit(main())
