"""GraphPort over Graphiti on Neo4j (LLD-1 §6, BD-11, AT-35): our UUIDs kept, no model
call, claim IDs returned by search, supersession as invalid_at without deletion, refused
relation pairs. Fictional Halden Bay data; deterministic embeddings (no model)."""

import os
import uuid
from collections.abc import AsyncIterator
from datetime import date

import pytest
from dotenv import dotenv_values

from app.adapters.graph.graphiti import GraphitiGraph, GraphWriteRefused
from app.domain.ids import graph_uuid
from app.ports.graph import GraphEdge, GraphEntity
from tests.support.workflow_fakes import HashEmbeddings

pytestmark = pytest.mark.stores

NEO4J_URI = os.environ.get("TEST_NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_PASSWORD = os.environ.get("TEST_NEO4J_PASSWORD") or dotenv_values(".env").get(
    "NEO4J_PASSWORD", ""
)


@pytest.fixture
async def graph() -> AsyncIterator[tuple[GraphitiGraph, str]]:
    g = GraphitiGraph(NEO4J_URI, "neo4j", NEO4J_PASSWORD or "", HashEmbeddings())
    try:
        await g.search_edges("probe", [])
    except Exception as exc:
        await g.close()
        message = f"Neo4j unreachable ({type(exc).__name__})"
        if os.environ.get("C4C_REQUIRE_DB") == "1":
            pytest.fail(message)
        pytest.skip(message + "; start it with `uv run poe up`")
    group = f"city_test_{uuid.uuid4().hex[:10]}"
    yield g, group
    await g.delete_group(group)
    await g.close()


def entity(group: str, key: str, name: str, kind: str) -> GraphEntity:
    return GraphEntity(
        uuid=graph_uuid(f"ent_{group}_{key}"),
        group_id=group,
        entity_type=kind,
        name=name,
        attributes={"entity_id": f"ent_{group}_{key}"},
    )


def edge(group: str, claim: str, name: str, fact: str, valid: date | None) -> GraphEdge:
    return GraphEdge(
        uuid=graph_uuid(claim),
        group_id=group,
        name=name,
        fact=fact,
        valid_at=valid,
        invalid_at=None,
        attributes={
            "claim_ids": [claim],
            "source_ids": ["src_1"],
            "status": "supported",
            "proxy_date": False,
        },
    )


async def test_triplet_keeps_our_uuids_and_claim_ids_come_back_from_search(
    graph: tuple[GraphitiGraph, str],
) -> None:
    g, group = graph
    city = entity(group, "city", "Halden Bay", "Place")
    office = entity(group, "office", "Halden Bay Health Office", "Organization")
    governs = edge(
        group,
        "clm_a",
        "GOVERNS",
        "The Halden Bay Health Office runs public health in Halden Bay.",
        date(2024, 4, 1),
    )

    assert await g.add_triplet(office, governs, city) == governs.uuid

    hits = await g.search_edges(group, ["GOVERNS"], query="Who runs public health in Halden Bay?")
    assert [h.edge.uuid for h in hits] == [governs.uuid]
    hit = hits[0]
    assert hit.edge.attributes["claim_ids"] == ["clm_a"]
    assert hit.edge.valid_at == date(2024, 4, 1)
    assert (hit.subject.uuid, hit.object.uuid) == (office.uuid, city.uuid)
    assert (hit.subject.entity_type, hit.object.name) == ("Organization", "Halden Bay")
    assert "fact_embedding" not in hit.edge.attributes


async def test_supersession_end_dates_without_deleting(graph: tuple[GraphitiGraph, str]) -> None:
    g, group = graph
    office = entity(group, "office", "Halden Bay Health Office", "Organization")
    marlow = entity(group, "marlow", "Ines Marlow", "Person")
    vell = entity(group, "vell", "Tomas Vell", "Person")
    old = edge(
        group,
        "clm_old",
        "LEADS",
        "Ines Marlow heads the Halden Bay Health Office.",
        date(2024, 4, 1),
    )
    new = edge(
        group,
        "clm_new",
        "LEADS",
        "Tomas Vell heads the Halden Bay Health Office.",
        date(2025, 9, 1),
    )
    await g.add_triplet(marlow, old, office)
    await g.add_triplet(vell, new, office)

    await g.invalidate_edge(old.uuid, date(2025, 9, 1))

    current = await g.search_edges(group, ["LEADS"])
    assert [h.edge.uuid for h in current] == [new.uuid]
    everything = await g.search_edges(group, ["LEADS"], include_ended=True)
    assert {h.edge.uuid for h in everything} == {old.uuid, new.uuid}
    ended = next(h for h in everything if h.edge.uuid == old.uuid)
    assert ended.edge.invalid_at == date(2025, 9, 1)
    as_of_2024 = await g.search_edges(group, ["LEADS"], as_of=date(2024, 12, 31))
    assert [h.edge.uuid for h in as_of_2024] == [old.uuid]
    by_query = await g.search_edges(group, ["LEADS"], query="Who heads the Health Office?")
    assert [h.edge.uuid for h in by_query] == [new.uuid]


async def test_contested_status_is_merged_into_the_edge(graph: tuple[GraphitiGraph, str]) -> None:
    g, group = graph
    city = entity(group, "city", "Halden Bay", "Place")
    office = entity(group, "office", "Halden Bay Health Office", "Organization")
    governs = edge(group, "clm_a", "GOVERNS", "The Health Office runs public health.", None)
    await g.add_triplet(office, governs, city)

    await g.update_edge_attributes(governs.uuid, {"status": "contested", "uuid": "ignored"})

    (hit,) = await g.search_edges(group, ["GOVERNS"])
    assert hit.edge.uuid == governs.uuid
    assert hit.edge.attributes["status"] == "contested"
    assert hit.edge.attributes["claim_ids"] == ["clm_a"]


async def test_pairs_outside_lld1_are_refused_before_the_graph(
    graph: tuple[GraphitiGraph, str],
) -> None:
    g, group = graph
    city = entity(group, "city", "Halden Bay", "Place")
    person = entity(group, "marlow", "Ines Marlow", "Person")
    with pytest.raises(GraphWriteRefused):
        await g.add_triplet(person, edge(group, "clm_x", "GOVERNS", "x", None), city)
    assert (await g.export_subgraph(group)).entities == []


async def test_neighbours_export_and_delete(graph: tuple[GraphitiGraph, str]) -> None:
    g, group = graph
    city = entity(group, "city", "Halden Bay", "Place")
    office = entity(group, "office", "Halden Bay Health Office", "Organization")
    programme = entity(group, "hearts", "Healthy Hearts Halden Bay", "Programme")
    await g.add_triplet(
        office, edge(group, "clm_1", "RUNS", "The office runs Healthy Hearts.", None), programme
    )
    await g.add_triplet(
        programme,
        edge(group, "clm_2", "OPERATES_IN", "Healthy Hearts operates in Halden Bay.", None),
        city,
    )

    around = await g.neighbours(group, programme.uuid)
    assert {h.edge.name for h in around} == {"RUNS", "OPERATES_IN"}
    export = await g.export_subgraph(group)
    assert {e.uuid for e in export.entities} == {city.uuid, office.uuid, programme.uuid}
    assert len(export.edges) == 2

    await g.delete_group(group)
    assert (await g.export_subgraph(group)).entities == []


async def test_the_embedding_marker_round_trips_and_is_restored(
    graph: tuple[GraphitiGraph, str],
) -> None:
    """R-82 (BD-14): the graph records the key of the model that made its embeddings.
    The marker is global to the graph, so the test runs only on a named test instance
    (TEST_NEO4J_URI, as CI sets): a developer's running app never sees it change (RV-104).
    The marker held before is put back afterwards."""
    if "TEST_NEO4J_URI" not in os.environ:
        pytest.skip("rewrites the graph's global marker: set TEST_NEO4J_URI to a test graph")
    g, _ = graph
    held = await g.embedding_marker()
    try:
        await g.set_embedding_marker("contract_test_key_v1")
        assert await g.embedding_marker() == "contract_test_key_v1"
    finally:
        if held is None:
            await g._g.driver.execute_query("MATCH (m:C4CMeta {name: 'embedding'}) DELETE m")
        else:
            await g.set_embedding_marker(held)
    assert await g.embedding_marker() == held
