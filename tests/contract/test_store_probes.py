"""Health probes against real stores (LLD-4 §7): the compose Qdrant and Neo4j locally,
service containers in CI. Skipped locally when a store is down; required in CI."""

import os
from collections.abc import AsyncIterator, Awaitable, Callable

import pytest
from dotenv import dotenv_values

from app.adapters.graph.neo4j_probe import Neo4jProbe
from app.adapters.vector.qdrant_probe import QdrantProbe
from app.ports.health import HealthProbe

pytestmark = pytest.mark.stores

QDRANT_URL = os.environ.get("TEST_QDRANT_URL", "http://127.0.0.1:6333")
NEO4J_URI = os.environ.get("TEST_NEO4J_URI", "bolt://127.0.0.1:7687")
# Locally the compose password is in .env; read without touching os.environ.
NEO4J_PASSWORD = os.environ.get("TEST_NEO4J_PASSWORD") or dotenv_values(".env").get(
    "NEO4J_PASSWORD", ""
)


async def _reachable_or_skip(probe: HealthProbe) -> HealthProbe:
    try:
        await probe.check()
    except Exception as exc:
        await probe.close()
        message = f"{probe.component} unreachable ({type(exc).__name__})"
        if os.environ.get("C4C_REQUIRE_DB") == "1":
            pytest.fail(message)
        pytest.skip(message + "; start it with `uv run poe up`")
    return probe


@pytest.fixture
async def qdrant() -> AsyncIterator[HealthProbe]:
    probe = await _reachable_or_skip(QdrantProbe(QDRANT_URL, None))
    yield probe
    await probe.close()


@pytest.fixture
async def neo4j() -> AsyncIterator[HealthProbe]:
    probe = await _reachable_or_skip(Neo4jProbe(NEO4J_URI, "neo4j", NEO4J_PASSWORD or ""))
    yield probe
    await probe.close()


async def test_qdrant_probe_succeeds(qdrant: HealthProbe) -> None:
    await qdrant.check()

    assert qdrant.component == "qdrant"


async def test_neo4j_probe_succeeds(neo4j: HealthProbe) -> None:
    await neo4j.check()

    assert neo4j.component == "neo4j"


@pytest.mark.parametrize(
    "make",
    [
        lambda: QdrantProbe("http://127.0.0.1:1", None, timeout_s=1),
        lambda: Neo4jProbe("bolt://127.0.0.1:1", "neo4j", "x", timeout_s=1),
    ],
    ids=["qdrant", "neo4j"],
)
async def test_probe_raises_when_store_unreachable(make: Callable[[], HealthProbe]) -> None:
    probe = make()
    check: Callable[[], Awaitable[None]] = probe.check
    try:
        with pytest.raises(Exception):  # noqa: B017, PT011 - any failure maps to "down"
            await check()
    finally:
        await probe.close()
