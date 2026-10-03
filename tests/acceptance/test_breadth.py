"""Breadth (D2-5, BD-14): every slot ends a run with one status and its history, re-plans
look for something new, one page is fetched once per run however many slots want it, the
budget stop still gives every slot a status, the run summary shows what happened, and a
programme's status follows its newest supported claim. Offline: scripted models, a
fictional web about Halden Bay, Norvania."""

from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from app.adapters.postgres.relational import PostgresRelational
from app.domain.vocab import EventType
from app.workflow.runner import RunManager
from tests.conftest import ConfigWriter
from tests.support.breadth import (
    CLOSED_HOST,
    CLOSED_URL,
    EMPTY_HOST,
    EMPTY_URL,
    PROGRAMME,
    PROGRAMME_URL,
    load_reference,
    ports_for,
    queries_for,
    run_to_end,
    scripts,
    search_for,
    settings_for,
    sparse_world,
)
from tests.support.thin_slice import Slice, query_rows, reachable_graph
from tests.support.workflow_fakes import MemoryVector

pytestmark = [pytest.mark.db, pytest.mark.stores]
SPARSE = {"S03": EMPTY_URL, "S08": EMPTY_URL, "S12": CLOSED_URL}


async def events(store: PostgresRelational, run_id: str) -> list[dict[str, Any]]:
    return await store.runs.events_after(run_id, 0, 10_000)


async def slot_rows(store: PostgresRelational, run_id: str) -> dict[str, dict[str, Any]]:
    return {r["slot_id"]: r for r in await store.runs.slot_results(run_id)}


async def sparse_run(
    relational: PostgresRelational,
    database_url: str,
    env: dict[str, str],
    slots: dict[str, str],
    config_dir: Path | None = None,
) -> tuple[str, Any, Any]:
    """One run over a sparse fictional web; returns the run ID, the web and the models."""
    await load_reference(relational)
    settings = settings_for(database_url, env, config_dir)
    world, models, graph = sparse_world(), scripts(), await reachable_graph()
    try:
        async with ports_for(
            relational, settings, world, search_for(slots), models, graph, MemoryVector()
        ) as ports:
            run_id = await run_to_end(RunManager(ports, settings), sorted(slots))
    finally:
        city = await relational.runs.city_for_place("9000001")
        if city:
            await graph.delete_group(city)
        await graph.close()
    return run_id, world, models


@pytest.fixture
async def sparse(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> tuple[str, Any, Any]:
    return await sparse_run(relational, migrated, valid_env, SPARSE)


async def test_sparse_city_lists_what_was_searched_and_invents_nothing(
    relational: PostgresRelational, sparse: tuple[str, Any, Any]
) -> None:
    """AT-16: a data-sparse city completes; the gaps say what was searched and why
    nothing was found; no figure is invented."""
    run_id, _, _ = sparse
    run = await relational.runs.run_row(run_id)
    assert run is not None
    assert run["status"] == "completed"
    assert await relational.research.claim_statuses(run_id) == {}  # nothing invented
    rows = await slot_rows(relational, run_id)
    for slot_id in ("S03", "S08"):
        assert rows[slot_id]["status"] == "answered_negative"
        assert rows[slot_id]["gap_note"].startswith("Searched 6 queries in ")
        assert "nothing acceptable found" in rows[slot_id]["gap_note"]
        assert rows[slot_id]["sources_checked"]  # the page that held nothing
    assert rows["S12"]["status"] == "blocked"
    assert rows["S12"]["gap_note"] == (
        "1 candidate sources refuse automated access (robots.txt disallows (1))."
    )


async def test_every_slot_has_one_status_with_its_queries_and_sources(
    relational: PostgresRelational, sparse: tuple[str, Any, Any]
) -> None:
    """AT-32: every slot of the run ends with exactly one status; a slot not answered
    lists the queries tried and the sources checked."""
    run_id, _, _ = sparse
    rows = await slot_rows(relational, run_id)
    assert set(rows) == set(SPARSE)
    for slot_id, row in rows.items():
        assert row["status"] != "answered"
        tried = [text for r in range(3) for text, _ in queries_for(slot_id, r)]
        texts = [t for t, _ in await relational.research.queries(row["queries_tried"])]
        assert sorted(texts) == sorted(tried)  # three rounds, no repeats
        assert row["replans_used"] == 2
    statuses = [e for e in await events(relational, run_id) if e["type"] == EventType.SLOT_STATUS]
    assert Counter(e["payload"]["slot_id"] for e in statuses) == {s: 3 for s in SPARSE}


async def test_replans_show_the_planner_what_was_tried(sparse: tuple[str, Any, Any]) -> None:
    """LLD-2 §11.3, LLD-3 §3.1: a re-plan round sees each slot's status, queries and gap
    note, and the country's government site filters (planner v2)."""
    _, _, models = sparse
    plans = [c.user for c in models.anthropic.calls if c.role == "planner"]
    assert [p.count("previous_attempts:") for p in plans] == [0, 1, 1]
    assert "S12: status blocked; queries tried: " in plans[1]
    assert "Halden Bay S03 evidence round 0" in plans[1]
    assert "government_sites: site:gov.xn" in plans[0]


async def test_a_page_is_fetched_once_however_many_slots_want_it(
    relational: PostgresRelational, sparse: tuple[str, Any, Any]
) -> None:
    """LLD-2 §14 step 1 (BD-14): two slots over three rounds read one fetched page; the
    second slot reuses the stored source instead of fetching it again."""
    run_id, world, models = sparse
    assert world.paths(EMPTY_HOST) == ["/robots.txt", "/annual-notes"]
    assert world.paths(CLOSED_HOST) == ["/robots.txt"]  # the gate refused the page
    sources = await query_rows(relational, "SELECT url FROM source WHERE run_id = :r", r=run_id)
    assert [s["url"] for s in sources] == [EMPTY_URL]
    extracted = {
        line
        for c in models.anthropic.calls
        if c.role == "extractor"
        for line in c.user.splitlines()
        if line.startswith("- S0")
    }
    assert {line[:5] for line in extracted} == {"- S03", "- S08"}  # both slots read it


async def test_the_run_summary_shows_outcomes_sources_cost_and_time(
    relational: PostgresRelational, sparse: tuple[str, Any, Any]
) -> None:
    """AT-38: claims by outcome, dropped by reason, blocked and unreachable sources, cost
    per model and time per stage."""
    run_id, _, _ = sparse
    run = await relational.runs.run_row(run_id)
    assert run is not None
    summary = run["summary"]
    assert summary["claims"] == {"dropped": 0}
    assert summary["dropped"] == {"geography_unresolved": 0}
    assert summary["sources"] == {
        "read": 1,
        "blocked": {"blocked_robots": 1},
        "unreachable": {},
        "unreadable": {},
    }
    assert summary["slots"] == {"answered_negative": 2, "blocked": 1}
    assert summary["models"]["claude-haiku-4-5-20251001"]["calls"] >= 3  # planner rounds
    assert summary["cost_usd"] > 0
    busy = summary["time"]["busy_ms"]
    assert set(busy) >= {"wave0", "planning", "search", "fetch", "extraction", "coverage"}
    assert summary["time"]["wall_clock_ms"] > 0
    finished = [e for e in await events(relational, run_id) if e["type"] == "run_finished"]
    assert finished[-1]["payload"]["summary"]["slots"] == summary["slots"]


async def test_a_tiny_budget_still_ends_with_every_slot_given_a_status(
    relational: PostgresRelational,
    migrated: str,
    valid_env: dict[str, str],
    write_config: ConfigWriter,
) -> None:
    """AT-19: with a deliberately tiny budget the run terminates with partial results and
    coverage status: stopped by its budget, every slot with a status, no re-plan."""

    def tiny(raw: dict[str, Any]) -> None:
        raw["budget"]["searches"] = 2

    run_id, _, models = await sparse_run(
        relational, migrated, valid_env, SPARSE, write_config(change=tiny)
    )
    run = await relational.runs.run_row(run_id)
    assert run is not None
    assert run["status"] == "stopped_by_budget"
    assert run["summary"]["budget"]["refused"] == ["searches"]
    assert set(await slot_rows(relational, run_id)) == set(SPARSE)
    log = await events(relational, run_id)
    warnings = [e["payload"] for e in log if e["type"] == EventType.BUDGET_WARNING]
    assert {"counter": "searches", "used": 2.0, "limit": 2.0} in warnings
    assert log[-1]["type"] == EventType.RUN_FINISHED
    assert len([c for c in models.anthropic.calls if c.role == "planner"]) == 1  # no re-plan
    searches = await query_rows(
        relational, "SELECT count(*) AS n FROM search_query WHERE run_id = :r", r=run_id
    )
    assert searches[0]["n"] == 2


async def test_a_programme_takes_the_status_of_its_newest_supported_claim(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> None:
    """T-06: a programme announced as planned and later reported running is shown as
    running, with the claim that says so (BD-19, BD-22)."""
    run_id, _, _ = await sparse_run(relational, migrated, valid_env, {"S07": PROGRAMME_URL})
    rows = await query_rows(
        relational,
        "SELECT attributes FROM entity WHERE entity_type = 'Programme' AND canonical_name = :n",
        n=PROGRAMME,
    )
    assert len(rows) == 1
    attributes = rows[0]["attributes"]
    assert attributes["status"] == "running"
    assert attributes["status_since"] == "2025-03-01"
    stated = await query_rows(
        relational,
        "SELECT c.claim_id, c.reference_end FROM claim c JOIN relation r USING (claim_id)"
        " WHERE c.run_id = :r AND r.programme_status = 'running'",
        r=run_id,
    )
    assert attributes["status_claim_id"] == stated[0]["claim_id"]
    # The page states no date, and none is guessed from its text (BD-22): the status is
    # observed as of its stated start
    assert stated[0]["reference_end"] is None
    assert attributes["status_as_of"] == "2025-03-01"
    assert (await slot_rows(relational, run_id))["S07"]["status"] == "answered"


async def test_the_thin_slice_slots_are_answered(thin_slice: Slice) -> None:
    """AT-32 on a run with findings: answered slots carry their best claims and no gap."""
    rows = await slot_rows(thin_slice.store, thin_slice.run_id)
    assert {s: r["status"] for s, r in rows.items()} == {"S01": "answered", "S04": "answered"}
    for row in rows.values():
        assert row["best_claim_ids"]
        assert row["gap_note"] is None
        assert row["replans_used"] == 0
