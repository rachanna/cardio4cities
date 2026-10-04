"""One embedding model per graph (R-82, BD-14, BD-25).

The graph stores entity and fact embeddings, so it records the key of the model that
made them. An empty graph takes the configured key. A graph that holds entities with no
marker, or another model's marker, must not receive this model's embeddings.

The check runs before every run starts or resumes, on the write path (BD-25): before,
it ran only at start-up, so a graph that was still starting at the first boot of a fresh
deploy never got its marker, a run then wrote entities, and the next start-up refused
the app. Start-up still checks, but only to warn: a graph problem refuses runs with a
clear 503, never the whole app.
"""

from app.ports.graph import GraphPort

PURGE_HINT = "run `uv run poe purge-graph` (local only), or point NEO4J_URI at an empty database"


class GraphNotReadyError(Exception):
    """The graph cannot take this run's writes; the message says why and what to do."""


async def ensure_graph_marker(graph: GraphPort | None, embedding_key: str) -> None:
    """Set the marker on an empty graph; raise GraphNotReadyError when the graph is
    unreachable, holds unmarked entities, or was made with another model."""
    if graph is None:
        raise GraphNotReadyError("no graph store is configured")
    try:
        marker = await graph.embedding_marker()
        if marker is None and not await graph.has_entities():
            await graph.set_embedding_marker(embedding_key)
            return
    except Exception as exc:  # unreachable: the run would write entities without a marker
        raise GraphNotReadyError(f"the graph could not be reached ({type(exc).__name__})") from exc
    if marker is None:
        raise GraphNotReadyError(
            f"the graph holds entities with no embedding marker, so they may come from "
            f"another embedding model than {embedding_key!r}: {PURGE_HINT}"
        )
    if marker != embedding_key:
        raise GraphNotReadyError(
            f"the graph's embeddings were made with {marker!r} but the configuration uses "
            f"{embedding_key!r}: {PURGE_HINT}"
        )
