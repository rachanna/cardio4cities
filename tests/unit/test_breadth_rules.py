"""Pure pieces of D2-5 (BD-14): programme status (T-06), the run's fetch cache, planner
v2 input and validation, stage timing, the graph's embedding marker (R-82) and the
purge-graph guard. Fixtures use the fictional Halden Bay, Norvania only."""

import asyncio
from datetime import date
from typing import Any

import pytest

from app.domain.vocab import ProgrammeStatus, SlotStatus
from app.main import check_graph_marker
from app.prompts.planner import context
from app.prompts.planner.schema import PlannedQuery, PlannerOutput, SlotQueries, validate
from app.workflow.fetch_cache import FetchCache
from app.workflow.graph_marker import GraphNotReadyError, ensure_graph_marker
from app.workflow.limits import StageClock
from app.workflow.rules.gap_notes import gap_note
from app.workflow.rules.programme_status import programme_status_update
from app.workflow.rules.selection import government_sites, publisher_table
from scripts import purge_graph

P = ProgrammeStatus

# --- programme status (T-06) -----------------------------------------------------------


def test_a_first_status_is_recorded_with_its_claim_and_date() -> None:
    assert programme_status_update({}, P.PLANNED, "clm_a", date(2023, 1, 1)) == {
        "status": "planned",
        "status_claim_id": "clm_a",
        "status_as_of": "2023-01-01",
        "status_since": None,
    }


def test_a_newer_claim_replaces_an_older_status_and_an_older_one_does_not() -> None:
    held = {"status": "planned", "status_claim_id": "clm_a", "status_as_of": "2023-01-01"}
    newer = programme_status_update(held, P.RUNNING, "clm_b", date(2025, 3, 1))
    assert newer is not None
    assert newer["status"] == "running"
    assert programme_status_update(held, P.ENDED, "clm_c", date(2022, 6, 1)) is None
    assert programme_status_update(held, P.ENDED, "clm_c", date(2023, 1, 1)) is None  # tie


def test_unknown_and_undated_claims_never_replace_a_stated_status() -> None:
    held = {"status": "running", "status_claim_id": "clm_a", "status_as_of": "2025-03-01"}
    assert programme_status_update(held, P.UNKNOWN, "clm_b", date(2026, 1, 1)) is None
    assert programme_status_update(held, P.ENDED, "clm_b", None) is None
    unknown = {"status": "unknown", "status_claim_id": "clm_a", "status_as_of": None}
    assert programme_status_update(unknown, P.PILOTING, "clm_b", None) is not None
    assert programme_status_update(unknown, P.UNKNOWN, "clm_b", None) is None


# --- fetch cache (LLD-2 §14 step 1) ----------------------------------------------------


async def test_the_first_slot_owns_a_url_and_the_next_waits_for_its_result() -> None:
    cache = FetchCache()
    assert cache.claim("http://a.halden-bay.test/x") is None  # the owner
    waiting = cache.claim("http://a.halden-bay.test/x")
    assert waiting is not None
    assert not waiting.done()
    cache.resolve("http://a.halden-bay.test/x", "src_1")
    assert await asyncio.wait_for(waiting, 1) == "src_1"


async def test_a_resumed_run_seeds_the_cache_from_stored_pages() -> None:
    cache = FetchCache()
    cache.seed({"http://a.halden-bay.test/x": "src_1", "http://a.halden-bay.test/y": None})
    assert cache.seeded
    assert cache.known("http://a.halden-bay.test/y")
    seeded = cache.claim("http://a.halden-bay.test/y")
    assert seeded is not None
    assert await seeded is None


# --- planner v2 (LLD-3 §3) ---------------------------------------------------------------

PUBLISHERS = {
    "deny": {"domains": []},
    "classes": {"government": {"suffixes": ["gov"], "second_level": ["gov", "go"]}},
}


def test_government_sites_are_generic_labels_under_the_country_code() -> None:
    assert government_sites(publisher_table(PUBLISHERS), "XN") == ["site:gov.xn", "site:go.xn"]


def output(*texts: str) -> PlannerOutput:
    queries = [PlannedQuery(text=t, lang="en", purpose="test") for t in texts]
    return PlannerOutput(slots=[SlotQueries(slot_id="S04", queries=queries)])


def test_a_site_filter_must_be_one_the_planner_was_given() -> None:
    sites = {"site:gov.xn"}
    fine = output("Halden Bay hypertension programme site:gov.xn", "Halden Bay survey")
    assert validate(fine, {"S04"}, set(), sites) == []
    made_up = output("Halden Bay hypertension site:health.example", "Halden Bay survey")
    assert validate(made_up, {"S04"}, set(), sites) == [
        "S04: site:health.example is not in government_sites"
    ]


def test_a_replan_line_names_status_queries_and_note() -> None:
    line = context.previous_attempt("S04", "answered_negative", ["q one", "q two"], "Searched 2")
    assert line == "S04: status answered_negative; queries tried: q one | q two; note: Searched 2"
    assert context.previous_attempt("S12", "blocked", [], None).endswith(
        "queries tried: none; note: none"
    )


# --- gap note after a budget stop (LLD-2 §11.4, BD-14) ----------------------------------


def test_a_budget_stop_is_named_in_the_gap_note() -> None:
    note = gap_note(SlotStatus.ANSWERED_NEGATIVE, n_queries=3, languages=["English"], unread=2)
    assert note is not None
    assert note.endswith("The run's budget ran out before 2 allowed sources could be read.")
    assert gap_note(SlotStatus.ANSWERED, unread=2) is None


# --- stage timing (AT-38) --------------------------------------------------------------


def test_busy_time_adds_up_per_stage_across_branches() -> None:
    now = [0.0]
    clock = StageClock(lambda: now[0])
    a, b = clock.start(), clock.start()  # two slots extracting side by side
    now[0] = 2.0
    clock.stop("extract", a)
    clock.stop("match_quotes", b)
    clock.stop("slot_done", a)  # bookkeeping: not a stage
    snapshot = clock.snapshot()
    assert snapshot["extraction"] == 4000
    assert snapshot["search"] == 0
    assert list(snapshot)[:2] == ["wave0", "planning"]


# --- graph embedding marker (R-82) -----------------------------------------------------


class Graph:
    def __init__(self, marker: str | None, entities: bool, fail: bool = False) -> None:
        self.marker, self.entities, self.fail = marker, entities, fail

    async def embedding_marker(self) -> str | None:
        if self.fail:
            raise ConnectionError("graph down")
        return self.marker

    async def set_embedding_marker(self, key: str) -> None:
        self.marker = key

    async def has_entities(self) -> bool:
        return self.entities


async def test_an_empty_graph_takes_the_configured_marker() -> None:
    graph = Graph(None, entities=False)
    assert await check_graph_marker(graph, "st_test_v1") is None  # type: ignore[arg-type]
    assert graph.marker == "st_test_v1"
    await ensure_graph_marker(graph, "st_test_v1")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("graph", "says"),
    [
        (Graph("openai_test_v1", entities=True), "made with 'openai_test_v1'"),
        (Graph(None, entities=True), "no embedding marker"),
        (Graph(None, entities=False, fail=True), "could not be reached"),
    ],
)
async def test_a_graph_from_another_model_refuses_runs_not_the_app(graph: Graph, says: str) -> None:
    """BD-25 (code review RV-014): start-up only warns; every run start refuses."""
    problem = await check_graph_marker(graph, "st_test_v1")  # type: ignore[arg-type]
    assert problem is not None
    assert says in problem
    with pytest.raises(GraphNotReadyError, match=says):
        await ensure_graph_marker(graph, "st_test_v1")  # type: ignore[arg-type]


async def test_a_graph_down_at_first_start_gets_its_marker_on_the_first_run() -> None:
    """RV-014: Neo4j still starting at the first boot used to leave the graph unmarked
    forever; the marker is now set on the write path."""
    graph = Graph(None, entities=False, fail=True)
    assert await check_graph_marker(graph, "st_test_v1") is not None  # type: ignore[arg-type]
    graph.fail = False  # the graph is up by the time a run starts
    await ensure_graph_marker(graph, "st_test_v1")  # type: ignore[arg-type]
    assert graph.marker == "st_test_v1"


def test_purge_graph_refuses_the_deployed_environment(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_ENV", "deployed")
    called: list[Any] = []
    monkeypatch.setattr(purge_graph, "purge", lambda: called.append(1))
    assert purge_graph.main() == 2
    assert called == []
    assert "refuses" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("uri", "local"),
    [
        ("bolt://127.0.0.1:7687", True),
        ("bolt://localhost:7687", True),
        ("bolt://[::1]:7687", True),
        ("neo4j+s://graph.halden-bay.test:7687", False),
        ("bolt://10.0.0.5:7687", False),
    ],
)
def test_purge_graph_takes_only_a_graph_on_this_machine(uri: str, local: bool) -> None:
    """RV-094: the guard checks the target, not only APP_ENV."""
    assert purge_graph.is_local(uri) is local


def test_purge_graph_refuses_a_remote_graph(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setattr(purge_graph, "graph_uri", lambda: "neo4j+s://graph.halden-bay.test")
    called: list[Any] = []
    monkeypatch.setattr(purge_graph, "purge", lambda uri: called.append(uri))
    assert purge_graph.main() == 2
    assert called == []
    assert "not on this machine" in capsys.readouterr().err
