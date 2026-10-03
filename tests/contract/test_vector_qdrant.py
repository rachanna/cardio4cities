"""VectorPort over Qdrant (AT-35, LLD-4 §8.2): idempotent upserts by point ID, and a
city filter that never returns another city's points. Uses the compose Qdrant locally,
a service container in CI."""

import os
import uuid
from collections.abc import AsyncIterator

import pytest

from app.adapters.vector.qdrant import QdrantVectorStore
from app.domain.ids import chunk_point_id
from app.ports.vector import VectorPoint

pytestmark = pytest.mark.stores
QDRANT_URL = os.environ.get("TEST_QDRANT_URL", "http://127.0.0.1:6333")


@pytest.fixture
async def store() -> AsyncIterator[tuple[QdrantVectorStore, str]]:
    adapter = QdrantVectorStore(QDRANT_URL, None)
    name = f"test_chunks__{uuid.uuid4().hex[:8]}"
    try:
        await adapter.ensure_collection(name, 4)
    except Exception as exc:
        await adapter.close()
        if os.environ.get("C4C_REQUIRE_DB") == "1":
            pytest.fail(f"qdrant unreachable: {exc}")
        pytest.skip("qdrant unreachable; start it with `uv run poe up`")
    yield adapter, name
    await adapter._client.delete_collection(name)
    await adapter.close()


def _point(source: str, index: int, city: str, vector: list[float]) -> VectorPoint:
    return VectorPoint(
        id=chunk_point_id(source, index),
        vector=vector,
        payload={
            "city_id": city,
            "run_id": "run_1",
            "source_id": source,
            "chunk_index": index,
            "text": f"chunk {index} of {source}",
        },
    )


async def test_upsert_is_idempotent_by_point_id(store: tuple[QdrantVectorStore, str]) -> None:
    adapter, name = store
    point = _point("src_a", 0, "city_hb", [1.0, 0.0, 0.0, 0.0])

    await adapter.upsert(name, [point])
    await adapter.upsert(name, [point])

    hits = await adapter.search(name, [1.0, 0.0, 0.0, 0.0], {"city_id": "city_hb"}, 10)
    assert [h.id for h in hits] == [point.id]


async def test_city_filter_never_returns_another_citys_points(
    store: tuple[QdrantVectorStore, str],
) -> None:
    adapter, name = store
    await adapter.upsert(
        name,
        [
            _point("src_a", 0, "city_hb", [1.0, 0.0, 0.0, 0.0]),
            _point("src_b", 0, "city_po", [1.0, 0.0, 0.0, 0.0]),
        ],
    )

    hits = await adapter.search(name, [1.0, 0.0, 0.0, 0.0], {"city_id": "city_hb"}, 10)

    assert {h.payload["city_id"] for h in hits} == {"city_hb"}


async def test_search_without_city_filter_is_refused(store: tuple[QdrantVectorStore, str]) -> None:
    adapter, name = store

    with pytest.raises(ValueError, match="city_id"):
        await adapter.search(name, [1.0, 0.0, 0.0, 0.0], {}, 10)


async def test_collection_dimension_and_delete_by_filter(
    store: tuple[QdrantVectorStore, str],
) -> None:
    adapter, name = store
    await adapter.upsert(name, [_point("src_a", 0, "city_hb", [0.0, 1.0, 0.0, 0.0])])

    await adapter.delete_by_filter(name, {"city_id": "city_hb"})

    assert await adapter.collection_dimension(name) == 4
    assert await adapter.collection_dimension("missing_collection") is None
    assert await adapter.search(name, [0.0, 1.0, 0.0, 0.0], {"city_id": "city_hb"}, 10) == []


def test_point_ids_are_deterministic() -> None:
    assert chunk_point_id("src_a", 3) == chunk_point_id("src_a", 3)
    assert chunk_point_id("src_a", 3) != chunk_point_id("src_a", 4)
