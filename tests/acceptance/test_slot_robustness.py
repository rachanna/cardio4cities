"""One bad item never costs a slot its round (BD-21; code review RV-010, RV-011, RV-041,
RV-051). One offline run of S04 where two search results redirect to the same page, a
search fails twice, one draft carries labels that cannot hold, and the checker crashes on
one claim. The page is stored once, the other claims are still checked, and every loss
is stored as an event and counted in the run summary. Fictional Halden Bay only."""

from typing import Any

from app.adapters.postgres.relational import PostgresRelational
from app.domain.vocab import ClaimKind, EventType, MeasureType
from app.ports.errors import ProviderUnavailableError
from app.ports.search import SearchHit
from app.prompts.checker.schema import CheckerOutput
from app.prompts.extractor.schema import ExtractorOutput, PopulationOut
from app.workflow.runner import RunManager
from tests.support import thin_slice
from tests.support.breadth import (
    load_reference,
    ports_for,
    queries_for,
    run_to_end,
    scripts,
    settings_for,
)
from tests.support.thin_slice import (
    FILLER,
    HOST,
    NEARBY_STATEMENT,
    TRUE_STATEMENT,
    URL,
    labels,
    page,
    query_rows,
    reachable_graph,
)
from tests.support.webworld import ALLOW_ALL, Reply, WebWorld
from tests.support.workflow_fakes import ListSearch, MemoryVector

OLD_URL = f"http://{HOST}/old-survey"
ALIAS_URL = f"http://{HOST}/survey-2024"
(EN_QUERY, _), (NV_QUERY, _) = queries_for("S04", 0)
INVERTED_STATEMENT = "Families of adults aged 70 to 30 in Halden Bay took part in the survey."


class FailingSearch(ListSearch):
    """Fails every attempt at the queries in `failing`."""

    def __init__(self, by_query: dict[str, list[str]], failing: set[str]) -> None:
        super().__init__([], by_query=by_query)
        self.failing = failing

    async def search(self, query: str, lang: str, limit: int = 10) -> list[SearchHit]:
        if query in self.failing:
            self.queries.append(query)
            raise ProviderUnavailableError("searxng: ConnectError")
        return await super().search(query, lang, limit)


def extractor(user: str) -> ExtractorOutput:
    out = thin_slice.extractor(user)
    inverted = labels(MeasureType.QUALITATIVE, None).model_copy(
        update={"population": PopulationOut(age_min=70, age_max=30, sex="all", group=None)}
    )
    return ExtractorOutput(claims=[*out.claims, thin_slice.claim(
        INVERTED_STATEMENT, FILLER.split(".")[0], kind=ClaimKind.STATEMENT, labels=inverted,
    )])  # fmt: skip


def checker(user: str) -> CheckerOutput:
    if NEARBY_STATEMENT in user:
        raise RuntimeError("the checker crashed on this claim")
    return thin_slice.checker(user)


async def test_one_bad_item_never_costs_the_slot_its_round(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> None:
    await load_reference(relational)
    settings = settings_for(migrated, valid_env)
    world = WebWorld()
    world.site(HOST, "93.184.216.34", {
        "/robots.txt": ALLOW_ALL,
        "/heart-survey": Reply(200, page()),
        "/old-survey": Reply(301, b"", None, {"location": URL}),
        "/survey-2024": Reply(301, b"", None, {"location": URL}),
    })  # fmt: skip
    search = FailingSearch({EN_QUERY: [OLD_URL, ALIAS_URL]}, failing={NV_QUERY})
    graph = await reachable_graph()
    try:
        async with ports_for(relational, settings, world, search,
                             scripts(extractor_=extractor, checker_=checker), graph,
                             MemoryVector()) as ports:  # fmt: skip
            run_id = await run_to_end(RunManager(ports, settings), ["S04"])
    finally:
        city = await relational.runs.city_for_place("9000001")
        if city:
            await graph.delete_group(city)
        await graph.close()

    # RV-010: two candidates, one page, one source; the round went on
    sources = await query_rows(
        relational, "SELECT url, url_canonical FROM source WHERE run_id = :r", r=run_id
    )
    assert [s["url_canonical"] for s in sources] == [URL]
    assert world.paths(HOST).count("/heart-survey") == 2  # each redirect fetched it once

    claims = await query_rows(
        relational, "SELECT statement, status FROM claim WHERE run_id = :r", r=run_id
    )
    status = {c["statement"]: c["status"] for c in claims}
    assert status[TRUE_STATEMENT] == "supported"  # checked after the crash on another claim
    assert status[NEARBY_STATEMENT] == "extracted"  # never a fact without a verdict
    assert INVERTED_STATEMENT not in status

    events = await relational.runs.events_after(run_id, 0, 10_000)
    dropped = [e["payload"] for e in events if e["type"] == EventType.CLAIM_DROPPED]
    assert "invalid_labels" in {p["reason"] for p in dropped}
    failed = [e["payload"] for e in events if e["type"] == EventType.STEP_FAILED]
    assert {(p["stage"], p["item"]) for p in failed} >= {("search", NV_QUERY)}
    assert any(p["stage"] == "verify" and p["error"] == "RuntimeError" for p in failed)
    assert all("crashed" not in str(p) for p in failed)  # a type, never a message

    # RV-041: the failed search was tried twice and is not a query tried
    assert search.queries.count(NV_QUERY) == 2
    tried = await query_rows(
        relational, "SELECT query FROM search_query WHERE run_id = :r", r=run_id
    )
    assert NV_QUERY not in {t["query"] for t in tried}

    # RV-051: the summary counts what was lost, by stage
    (row,) = await query_rows(
        relational, "SELECT summary FROM run_summary WHERE run_id = :r", r=run_id
    )
    summary: dict[str, Any] = row["summary"]
    assert summary["failed_steps"]["search"] >= 1
    assert summary["failed_steps"]["verify"] == 1
