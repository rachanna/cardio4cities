"""Deterministic identifiers (LLD-1 §0, §5.1). Pure: the same input always gives the
same UUID, so re-upserts are idempotent and graph identity stays ours (HD-06)."""

import uuid

# Fixed namespace for every uuid5 in the system; never change it, or stored IDs drift.
NAMESPACE = uuid.UUID("6f1c2a52-8d0b-5a3e-9c47-c4c1f0a1e2b3")


def chunk_point_id(source_id: str, chunk_index: int) -> str:
    """Qdrant point ID for one chunk of one source (LLD-1 §5.1)."""
    return str(uuid.uuid5(NAMESPACE, f"{source_id}:{chunk_index}"))


def graph_uuid(our_id: str) -> str:
    """Graphiti node or edge UUID from an entity or claim ID (LLD-1 §0)."""
    return str(uuid.uuid5(NAMESPACE, our_id))
