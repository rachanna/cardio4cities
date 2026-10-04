"""Resume after a crash (LLD-2 §17, BD-14): a run stopped partway by the process going
down is resumed once at start-up from its LangGraph checkpoint (real Postgres, schema
`lg`), and finishes with no duplicate searches, sources, claims, events, graph edges or
claim-index points. A run that cannot be resumed is marked failed, visibly.

The thin-slice world (slots S04 and S01, Halden Bay, Norvania) is reused; the "crash" is
the run's task being cancelled at the first checker call, as a shutdown would."""

import asyncio
from collections import Counter
from collections.abc import AsyncIterator
from typing import Any

import pytest

from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser
from app.adapters.postgres.checkpointer import PostgresCheckpointer
from app.adapters.postgres.relational import PostgresRelational
from app.adapters.snapshots.postgres import PostgresSnapshots
from app.domain.models import CityIdentity
from app.domain.vocab import EventType, VerdictLabel
from app.prompts.checker.schema import CheckerOutput, CheckIssue
from app.workflow.runner import RunManager
from app.workflow.state import CHECKPOINT_TYPES
from tests.support.breadth import load_reference, settings_for
from tests.support.thin_slice import (
    EN_GOV_QUERY,
    GOV_URL,
    HOST,
    SECOND_GOV_QUERY,
    URL,
    checker,
    extractor,
    governance_page,
    page,
    planner,
    query_rows,
    reachable_graph,
)
from tests.support.webworld import ALLOW_ALL, Reply, WebWorld
from tests.support.workflow_fakes import (
    HashEmbeddings,
    ListSearch,
    MemoryVector,
    Ports,
    ScriptedLLM,
)

pytestmark = [pytest.mark.db, pytest.mark.stores]


class Shutdown:
    """The checker's first call stops the process: the run's task is cancelled from
    outside, as a shutdown would, while the node is in flight."""

    def __init__(self) -> None:
        self.manager: RunManager | None = None

    def __call__(self, user: str) -> CheckerOutput:
        assert self.manager is not None
        for task in self.manager.tasks.values():
            task.cancel()
        return checker(user)


@pytest.fixture
async def checkpointer(migrated: str) -> AsyncIterator[PostgresCheckpointer]:
    saver = PostgresCheckpointer(migrated, CHECKPOINT_TYPES)
    yield saver
    await saver.close()


def world() -> WebWorld:
    web = WebWorld()
    web.site(
        HOST,
        "93.184.216.34",
        {
            "/robots.txt": ALLOW_ALL,
            "/heart-survey": Reply(200, page()),
            "/public-health": Reply(200, governance_page()),
        },
    )
    return web


async def duplicates(store: PostgresRelational, sql: str, run_id: str) -> list[dict[str, Any]]:
    return await query_rows(store, sql, r=run_id)


async def test_a_crashed_run_resumes_once_without_duplicates(
    relational: PostgresRelational,
    migrated: str,
    valid_env: dict[str, str],
    checkpointer: PostgresCheckpointer,
) -> None:
    await load_reference(relational)
    settings = settings_for(migrated, valid_env)
    graph = await reachable_graph()
    vector = MemoryVector()
    snapshots = PostgresSnapshots(migrated, settings.config.snapshots.max_bytes)
    search = ListSearch([URL], by_query={EN_GOV_QUERY: [GOV_URL], SECOND_GOV_QUERY: [GOV_URL]})
    web = world()

    def ports(check: Any) -> Ports:
        return Ports(
            relational=relational,
            llm={
                "anthropic": ScriptedLLM("anthropic", {"planner": planner, "extractor": extractor}),
                "openai": ScriptedLLM("openai", {"checker": check}),
            },
            search=search,
            fetch=web.fetcher(),
            robots=ProtegoRobotsParser(),
            parser=DocumentParser(),
            embeddings=HashEmbeddings(),
            vector=vector,
            snapshots=snapshots,
            graph=graph,
            checkpointer=checkpointer,
        )

    city_id = None
    try:
        with web.running():
            shutdown = Shutdown()
            first = RunManager(ports(shutdown), settings)
            shutdown.manager = first
            started = await first.start("9000001", slots=["S04", "S01"])
            city_id = started.city_id
            with pytest.raises(asyncio.CancelledError):
                await first.wait(started.run_id)
            run_id = started.run_id
            stranded = await relational.runs.run_row(run_id)
            assert stranded is not None
            assert stranded["status"] == "running"
            before = await duplicates(
                relational, "SELECT count(*) AS n FROM claim WHERE run_id = :r", run_id
            )
            assert before[0]["n"] > 0  # the crash came after real work

            resumed_ports = ports(checker)
            restarted = RunManager(resumed_ports, settings)  # a new process
            assert await restarted.resume_stranded(stale_after_s=0) == [run_id]  # a new process
            await restarted.wait(run_id)
            # From the checkpoint, not from the start: the plan made before the stop holds
            scripted = resumed_ports.llm["anthropic"]
            assert isinstance(scripted, ScriptedLLM)
            assert [c for c in scripted.calls if c.role == "planner"] == []
    finally:
        if city_id:
            await graph.delete_group(city_id)
        await graph.close()
        await snapshots.close()

    run = await relational.runs.run_row(run_id)
    assert run is not None
    assert run["status"] == "completed"
    assert run["resume_attempts"] == 1
    for sql in (
        "SELECT url FROM source WHERE run_id = :r GROUP BY url HAVING count(*) > 1",
        "SELECT slot_id, statement FROM claim WHERE run_id = :r"
        " GROUP BY slot_id, statement HAVING count(*) > 1",
        "SELECT slot_id, replan_round, query FROM search_query WHERE run_id = :r"
        " GROUP BY 1, 2, 3 HAVING count(*) > 1",
        "SELECT url, outcome FROM crawl_decision WHERE run_id = :r"
        " GROUP BY url, outcome HAVING count(*) > 1",
        "SELECT g.claim_id FROM graph_link g JOIN claim c USING (claim_id)"
        " WHERE c.run_id = :r GROUP BY g.claim_id HAVING count(*) > 1",
    ):
        assert await duplicates(relational, sql, run_id) == [], sql
    sources = await duplicates(
        relational, "SELECT count(*) AS n FROM source WHERE run_id = :r", run_id
    )
    assert sources[0]["n"] == 2
    assert web.paths(HOST).count("/heart-survey") == 1  # never fetched twice

    log = await relational.runs.events_after(run_id, 0, 10_000)
    assert [e["seq"] for e in log] == list(range(1, len(log) + 1))
    kinds = Counter(e["type"] for e in log)
    assert kinds[EventType.RUN_STARTED] == 1
    assert kinds[EventType.RUN_FINISHED] == 1
    assert kinds[EventType.SEARCH_DONE] == 4
    assert kinds[EventType.SOURCE_FETCHED] == 2
    per_claim = Counter(
        (e["type"], e["payload"]["claim_id"])
        for e in log
        if e["type"] in (EventType.CLAIM_EXTRACTED, EventType.CLAIM_VERDICT, EventType.FACT_WRITTEN)
    )
    assert max(per_claim.values()) == 1

    links = await duplicates(
        relational,
        "SELECT g.edge_uuid FROM graph_link g JOIN claim c USING (claim_id) WHERE c.run_id = :r",
        run_id,
    )
    assert links  # facts reached the graph
    indexed = [p.id for points in vector.points.values() for p in points]
    assert len(indexed) == len(set(indexed))

    # Resumed once already: a second stop is not resumed again
    await relational.runs.set_status(run_id, "running")
    again = RunManager(no_ports(relational, checkpointer), settings)
    assert await again.resume_stranded(stale_after_s=0) == []
    failed = await relational.runs.run_row(run_id)
    assert failed is not None
    assert failed["error"] == ("interrupted by a restart (already resumed once)")


def no_ports(relational: PostgresRelational, checkpointer: PostgresCheckpointer) -> Ports:
    """Only what `resume_stranded` reads before deciding a run cannot resume."""
    return Ports(relational, {}, None, None, None, None, None, None, None, None,
                 checkpointer=checkpointer)  # fmt: skip


async def test_a_run_that_cannot_resume_is_marked_failed(
    relational: PostgresRelational,
    migrated: str,
    valid_env: dict[str, str],
    checkpointer: PostgresCheckpointer,
) -> None:
    """No checkpoint (the process stopped before the first step was saved, or ran
    without a checkpointer): the run fails visibly instead of hanging as `running`."""
    await load_reference(relational)
    place = await relational.reference.place_identity("9000001")
    assert place is not None
    await relational.runs.create_city(CityIdentity(city_id="city_T", admin2_name=None, **place))
    await relational.runs.create_run("run_T", "city_T", {}, {})
    await relational.runs.set_status("run_T", "running")

    restarted = RunManager(no_ports(relational, checkpointer), settings_for(migrated, valid_env))
    assert await restarted.resume_stranded() == []
    run = await relational.runs.run_row("run_T")
    assert run is not None
    assert run["status"] == "failed"
    assert run["error"] == "interrupted by a restart (no checkpoint)"
    log = await relational.runs.events_after("run_T", 0, 10_000)
    assert log[-1]["type"] == EventType.RUN_FINISHED
    assert log[-1]["payload"]["status"] == "failed"


def refuting(_: str) -> CheckerOutput:
    return CheckerOutput(
        label=VerdictLabel.REFUTED,
        rationale="Not what the passage says.",
        scope_verified=False,
        period_verified=False,
        issues=[CheckIssue.CONTRADICTED],
    )


async def test_a_stop_after_a_verdict_is_stored_keeps_that_verdict(
    relational: PostgresRelational,
    migrated: str,
    valid_env: dict[str, str],
    checkpointer: PostgresCheckpointer,
) -> None:
    """RV-004, RV-063 (BD-18): the process stops after the checker's verdict is stored and
    before the claim's status is set. The resumed run applies the stored verdict and never
    asks the checker again, so a refuted claim cannot come back as a fact, even when the
    checker would now say supported."""
    await load_reference(relational)
    settings = settings_for(migrated, valid_env)
    graph = await reachable_graph()
    snapshots = PostgresSnapshots(migrated, settings.config.snapshots.max_bytes)
    search = ListSearch([URL], by_query={EN_GOV_QUERY: [GOV_URL], SECOND_GOV_QUERY: [GOV_URL]})
    web = world()
    research = relational.research
    original = research.set_claim_status
    stopped: dict[str, Any] = {}

    def ports(check: Any) -> Ports:
        return Ports(
            relational=relational,
            llm={
                "anthropic": ScriptedLLM("anthropic", {"planner": planner, "extractor": extractor}),
                "openai": ScriptedLLM("openai", {"checker": check}),
            },
            search=search,
            fetch=web.fetcher(),
            robots=ProtegoRobotsParser(),
            parser=DocumentParser(),
            embeddings=HashEmbeddings(),
            vector=MemoryVector(),
            snapshots=snapshots,
            graph=graph,
            checkpointer=checkpointer,
        )

    async def stop_at_first_status(claim_id: str, status: str) -> None:
        stopped["claim"] = claim_id  # its verdict is committed; the status is not
        research.set_claim_status = original  # type: ignore[method-assign]
        for task in stopped["manager"].tasks.values():
            task.cancel()
        await asyncio.sleep(0)
        await original(claim_id, status)

    city_id = None
    try:
        with web.running():
            first = RunManager(ports(refuting), settings)
            stopped["manager"] = first
            research.set_claim_status = stop_at_first_status  # type: ignore[method-assign]
            started = await first.start("9000001", slots=["S04", "S01"])
            city_id, run_id = started.city_id, started.run_id
            with pytest.raises(asyncio.CancelledError):
                await first.wait(run_id)
            research.set_claim_status = original  # type: ignore[method-assign]
            resumed_ports = ports(checker)  # this checker would say supported
            restarted = RunManager(resumed_ports, settings)
            assert await restarted.resume_stranded(stale_after_s=0) == [run_id]  # a new process
            await restarted.wait(run_id)
    finally:
        research.set_claim_status = original  # type: ignore[method-assign]
        if city_id:
            await graph.delete_group(city_id)
        await graph.close()
        await snapshots.close()

    claim_id = stopped["claim"]
    (row,) = await query_rows(
        relational,
        "SELECT c.status, v.label FROM claim c JOIN verdict v USING (claim_id)"
        " WHERE c.claim_id = :c",
        c=claim_id,
    )
    assert (row["status"], row["label"]) == ("refuted", "refuted")
    rows = await query_rows(
        relational,
        "SELECT c.status, v.label FROM claim c JOIN verdict v USING (claim_id) WHERE c.run_id = :r",
        r=run_id,
    )
    passed = {"supported", "contested", "superseded"}  # statuses only a supported verdict gives
    assert all((r["status"] in passed) == (r["label"] == "supported") for r in rows), rows
    shown = await query_rows(
        relational, "SELECT claim_id FROM v_city_facts WHERE run_id = :r", r=run_id
    )
    assert claim_id not in {s["claim_id"] for s in shown}
    resumed = resumed_ports.llm["openai"]
    assert isinstance(resumed, ScriptedLLM)
    statement = await query_rows(
        relational, "SELECT statement FROM claim WHERE claim_id = :c", c=claim_id
    )
    assert not any(
        statement[0]["statement"] in c.user for c in resumed.calls if c.role == "checker"
    )  # the checker was never asked about it again
