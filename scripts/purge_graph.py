"""`poe purge-graph`: delete everything in the local Neo4j graph, the embedding marker too
(R-82, BD-14), and the Postgres graph links that pointed into it. Start-up refuses a graph
whose embeddings came from another model; this is the fix for a local database. Refuses a
graph that is not on this machine (a loopback address), and APP_ENV `deployed`.

Postgres and Qdrant keep every claim and fact. A fact's edge is written by the run that
confirmed it, and `brief_ready` retries only its own run's edges: facts from earlier runs
have no edge until their city is researched again (BD-36)."""

import asyncio
import ipaddress
import os
import sys
from urllib.parse import urlsplit

from dotenv import load_dotenv

from app.adapters.graph.graphiti import GraphitiGraph
from app.settings import load_settings
from scripts.reference._db import relational_from_env


class _NoEmbeddings:
    """Purging embeds nothing."""

    dimension = 0
    key = "none"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("purge-graph embeds nothing")


def is_local(uri: str) -> bool:
    """The graph is on this machine: a loopback host, never a remote or managed one."""
    host = urlsplit(uri).hostname or ""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def graph_uri() -> str:
    settings = load_settings()
    return settings.secret(settings.config.graph.uri_env)


async def purge(uri: str) -> tuple[int, int]:
    settings = load_settings()
    graph_cfg = settings.config.graph
    graph = GraphitiGraph(
        uri,
        settings.secret(graph_cfg.user_env),
        settings.secret(graph_cfg.password_env),
        _NoEmbeddings(),
    )
    relational = relational_from_env()
    try:
        nodes = await graph.purge()
        links = await relational.research.clear_graph_links()
        return nodes, links
    finally:
        await graph.close()
        await relational.close()


def main() -> int:
    load_dotenv(".env", override=False)
    if os.environ.get("APP_ENV", "local") == "deployed":
        print("purge-graph refuses to run with APP_ENV=deployed", file=sys.stderr)
        return 2
    uri = graph_uri()
    if not is_local(uri):
        print("purge-graph refuses a graph that is not on this machine", file=sys.stderr)
        return 2
    nodes, links = asyncio.run(purge(uri))
    print(
        f"graph purged: {nodes} nodes deleted, {links} graph links cleared; "
        "the next start-up writes a new marker"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
