"""`poe purge CITY` (LLD-1 §8, BD-36, BD-42; D4-7 removes rehearsal cities with it).
On real Postgres and Neo4j with the Halden Bay retrieval fixture, a second fictional city
alongside, and LangGraph checkpoints for both: the purged city leaves nothing in any
store, and the other city is untouched."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy import text

from app.adapters.graph.graphiti import GraphitiGraph
from app.adapters.postgres.checkpointer import PostgresCheckpointer
from app.adapters.postgres.relational import PostgresRelational
from app.domain.models import CityIdentity
from app.ports.vector import VectorPoint
from app.workflow.state import CHECKPOINT_TYPES
from scripts import eval_rag
from scripts.purge_city import PurgeRefused, purge_city
from scripts.reference.yaml_reference import read_indicators, read_slots
from tests.support.gazetteer import NEAR_TOWN, PLACE, TOWN, sync_gazetteer
from tests.support.thin_slice import reachable_graph
from tests.support.workflow_fakes import HashEmbeddings, MemoryVector

pytestmark = [pytest.mark.db, pytest.mark.stores]
CITY = eval_rag.CITY_ID
OTHER = "city_purge_port_ostra"
OTHER_RUN = "run_purge_port_ostra"
CHUNKS = "source_chunks__test"


async def _tables(store: PostgresRelational) -> list[str]:
    async with store._engine.connect() as conn:
        rows = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.columns WHERE table_schema = 'c4c'"
                " AND column_name IN ('city_id', 'run_id') GROUP BY table_name"
            )
        )
        return [r[0] for r in rows if not r[0].startswith("v_")]


async def _rows_of(store: PostgresRelational, city_id: str, run_ids: list[str]) -> int:
    total = 0
    async with store._engine.connect() as conn:
        for table in await _tables(store):
            cols = {
                r[0]
                for r in await conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns"
                        " WHERE table_schema = 'c4c' AND table_name = :t"
                    ),
                    {"t": table},
                )
            }
            where = "city_id = :c" if "city_id" in cols else "run_id = ANY(:r)"
            sql = f"SELECT count(*) FROM {table} WHERE {where}"  # noqa: S608 - schema names
            total += (await conn.execute(text(sql), {"c": city_id, "r": run_ids})).scalar_one()
        for table in ("checkpoints", "checkpoint_writes", "checkpoint_blobs"):
            sql = f"SELECT count(*) FROM lg.{table} WHERE thread_id = ANY(:r)"  # noqa: S608
            total += (await conn.execute(text(sql), {"r": run_ids})).scalar_one()
    return total


async def _clear_checkpoints(store: PostgresRelational, threads: list[str]) -> None:
    async with store._engine.begin() as conn:
        for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
            sql = f"DELETE FROM lg.{table} WHERE thread_id = ANY(:r)"  # noqa: S608
            await conn.execute(text(sql), {"r": threads})


@pytest.fixture
async def world(migrated: str) -> AsyncIterator[dict[str, Any]]:
    store = PostgresRelational(migrated)
    await store.reference.sync_indicators(read_indicators())
    await store.reference.sync_slots(read_slots())
    await sync_gazetteer(store, PLACE + TOWN + NEAR_TOWN)
    graph: GraphitiGraph = await reachable_graph()
    await graph.delete_group(CITY)
    embeddings, vector = HashEmbeddings(), MemoryVector()
    claims = f"claim_index__{embeddings.key}"
    loaded = await eval_rag.load_fixture(store, graph, vector, embeddings, claims)
    runs = list(loaded["runs"].values())

    place = await store.reference.place_identity("9000002")
    assert place is not None
    await store.runs.create_city(CityIdentity(city_id=OTHER, admin2_name=None, **place))
    await store.runs.create_run(OTHER_RUN, OTHER, {}, {})
    await store.runs.append_event(OTHER_RUN, "evt_purge_other", "run_started", {})
    await store.runs.set_status(OTHER_RUN, "completed")

    await vector.ensure_collection(CHUNKS, embeddings.dimension)
    await vector.upsert(
        CHUNKS,
        [
            VectorPoint(id=f"chunk_{c}", vector=[1.0] * embeddings.dimension,
                        payload={"city_id": c})
            for c in (CITY, OTHER)
        ],
    )  # fmt: skip

    checkpointer = PostgresCheckpointer(migrated, CHECKPOINT_TYPES)
    saver = await checkpointer.saver()
    threads = [*runs, OTHER_RUN, "run_purge_in_progress"]
    await _clear_checkpoints(store, threads)  # schema lg outlives the rebuilt schema c4c
    for run_id in (*runs, OTHER_RUN):
        config = {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}}
        await saver.aput(config, empty_checkpoint(), {}, {})  # type: ignore[arg-type]
    try:
        yield {
            "store": store, "graph": graph, "vector": vector, "runs": runs,
            "collections": [CHUNKS, claims, "claim_index__never_created"],
        }  # fmt: skip
    finally:
        await _clear_checkpoints(store, threads)
        await checkpointer.close()
        await graph.delete_group(CITY)
        await graph.close()
        await store.close()


async def test_a_purged_city_leaves_nothing_in_any_store(world: dict[str, Any]) -> None:
    store, graph, vector = world["store"], world["graph"], world["vector"]
    assert await _rows_of(store, CITY, world["runs"]) > 0
    assert (await graph.export_subgraph(CITY)).entities
    before = await store.purge.counts(CITY)
    assert before["claim"] > 0
    assert before["run"] == len(world["runs"])
    assert await store.purge.counts(CITY) == before  # the dry run reads, never deletes

    outcome = await purge_city(CITY, store, vector, graph, world["collections"])

    assert await _rows_of(store, CITY, world["runs"]) == 0
    assert await store.purge.city(CITY) is None
    assert not (await graph.export_subgraph(CITY)).entities
    for name in (CHUNKS, world["collections"][1]):
        assert not [p for p in vector.points.get(name, []) if p.payload.get("city_id") == CITY]
    assert outcome.collections == [CHUNKS, world["collections"][1]]  # a missing one is skipped
    assert outcome.rows["claim"] > 0
    assert outcome.rows["city"] == 1
    assert outcome.rows["lg.checkpoints"] == len(world["runs"])

    # The other city keeps its rows, its point and its checkpoint
    assert await _rows_of(store, OTHER, [OTHER_RUN]) > 0
    assert await store.purge.city(OTHER) is not None
    assert [p.payload["city_id"] for p in vector.points[CHUNKS]] == [OTHER]


async def test_a_city_with_a_run_in_progress_is_refused(world: dict[str, Any]) -> None:
    store = world["store"]
    await store.runs.create_run("run_purge_in_progress", OTHER, {}, {})  # queued

    with pytest.raises(PurgeRefused, match="queued or running"):
        await purge_city(OTHER, store, world["vector"], world["graph"], world["collections"])
    assert await store.purge.city(OTHER) is not None


async def test_an_unknown_city_is_refused(world: dict[str, Any]) -> None:
    with pytest.raises(PurgeRefused, match="no city"):
        await purge_city(
            "city_nowhere", world["store"], world["vector"], world["graph"], world["collections"]
        )
