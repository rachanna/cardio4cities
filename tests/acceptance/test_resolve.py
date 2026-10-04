"""AT-24, the API half: an ambiguous name is never resolved silently (R-57; code review
RV-103). Real trigram search in Postgres over a fictional gazetteer with two places named
Halden Bay. The UI half (the chosen identity shown before research) belongs to D3-4."""

import asyncio
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.adapters.postgres.relational import PostgresRelational
from app.main import create_app
from tests.support.gazetteer import NEAR_TOWN, PLACE, TOWN, _line, sync_gazetteer
from tests.unit.fake_adapters import probes as fake_probes
from tests.unit.test_api import REGISTRY

pytestmark = pytest.mark.db

# A second, smaller Halden Bay, inland and about 150 km from the first
NAMESAKE = _line(
    "9000006", "Halden Bay", "Halden Bay", "", "61.2", "7.4", "P", "PPL", "XN", "",
    "02", "", "", "", "9000", "", "5", "Etc/UTC", "2026-01-01",
)  # fmt: skip


async def _seed(database_url: str) -> None:
    store = PostgresRelational(database_url)
    try:
        await sync_gazetteer(store, PLACE + TOWN + NEAR_TOWN + NAMESAKE)
    finally:
        await store.close()


@pytest.fixture
def resolver(
    migrated: str, valid_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    """A signed-in client whose place search is the real Postgres one."""
    asyncio.run(_seed(migrated))
    for name, value in valid_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(fake_probes, "DOWN", set())
    with TestClient(
        create_app(env_file=None, registry=REGISTRY), base_url="https://testserver"
    ) as client:
        store = PostgresRelational(migrated)  # its connections open on the client's loop
        client.app.state.container.relational = store  # type: ignore[attr-defined]
        client.post("/api/v1/session", json={"access_code": valid_env["ACCESS_CODE"]})
        try:
            yield client
        finally:
            client.portal.call(store.close)  # type: ignore[union-attr]


def resolve(client: TestClient, query: str) -> dict[str, object]:
    response = client.post("/api/v1/cities/resolve", json={"query": query})
    assert response.status_code == 200
    body: dict[str, object] = response.json()
    return body


def test_a_shared_name_lists_every_place_told_apart_and_is_not_exact(
    resolver: TestClient,
) -> None:
    """AT-24: both places named Halden Bay come back first, larger first, each with its
    region and coordinates; the name alone does not choose one."""
    body = resolve(resolver, "halden bay")
    assert body["exact"] is False
    candidates = body["candidates"]
    assert isinstance(candidates, list)
    first, second = candidates[0], candidates[1]
    assert (first["gazetteer_id"], second["gazetteer_id"]) == ("9000001", "9000006")
    assert (first["admin1_name"], second["admin1_name"]) == ("West Coast", "Inland")
    assert (first["lat"], first["lon"]) != (second["lat"], second["lon"])
    assert first["population"] > second["population"]


def test_a_unique_name_is_exact(resolver: TestClient) -> None:
    body = resolve(resolver, "Kestrel Point")
    assert body["exact"] is True
    candidates = body["candidates"]
    assert isinstance(candidates, list)
    assert candidates[0]["gazetteer_id"] == "9000005"


def test_a_misspelt_name_offers_candidates_by_trigram_and_is_not_exact(
    resolver: TestClient,
) -> None:
    body = resolve(resolver, "Haldn Bay")
    assert body["exact"] is False
    candidates = body["candidates"]
    assert isinstance(candidates, list)
    assert {c["gazetteer_id"] for c in candidates} >= {"9000001", "9000006"}


def test_an_alternate_name_finds_its_place_without_claiming_an_exact_match(
    resolver: TestClient,
) -> None:
    body = resolve(resolver, "Haldenbukt")
    assert body["exact"] is False  # the user sees the identity chosen before research
    candidates = body["candidates"]
    assert isinstance(candidates, list)
    assert candidates[0]["gazetteer_id"] == "9000001"
