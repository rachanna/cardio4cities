"""AT-01: research happens live, at request time (R-01, R-10; code review RV-064).
Offline: the thin slice's fictional web about Halden Bay, Norvania."""

import time

import pytest

from app.adapters.postgres.relational import PostgresRelational
from tests.support.thin_slice import query_rows, run_slice

pytestmark = [pytest.mark.db, pytest.mark.stores]
PLACE = "9000001"
CITY_TABLES = ("city", "run", "search_query", "crawl_decision", "source", "claim")
TIMES = (
    "SELECT created_at AS t FROM search_query WHERE run_id = :r",
    "SELECT decided_at AS t FROM crawl_decision WHERE run_id = :r",
    "SELECT retrieved_at AS t FROM source WHERE run_id = :r",
)


async def test_unseen_city_fetches_after_request(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> None:
    """AT-01: from empty stores, every outbound request and every record of the city comes
    after the run was requested; nothing about the city existed before."""
    assert await relational.runs.city_for_place(PLACE) is None
    for table in CITY_TABLES:
        rows = await query_rows(relational, f"SELECT count(*) AS n FROM {table}")  # noqa: S608
        assert rows[0]["n"] == 0, table
    requested_db = (await query_rows(relational, "SELECT now() AS t"))[0]["t"]
    requested = time.monotonic()

    async with run_slice(relational, migrated, valid_env) as s:
        assert s.world is not None
        assert s.world.log  # the fictional web was asked, live
        assert all(hit.at >= requested for hit in s.world.log)
        assert s.search.queries
        assert s.city_id == await relational.runs.city_for_place(PLACE)
        city = await query_rows(
            relational, "SELECT created_at FROM city WHERE city_id = :c", c=s.city_id
        )
        assert city[0]["created_at"] >= requested_db
        run = await relational.runs.run_row(s.run_id)
        assert run is not None
        assert run["started_at"] >= requested_db
        for sql in TIMES:
            times = [r["t"] for r in await query_rows(relational, sql, r=s.run_id)]
            assert times, sql
            assert all(t >= requested_db for t in times), sql
        assert await relational.research.claim_statuses(s.run_id)  # records exist only now
