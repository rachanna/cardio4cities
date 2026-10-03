"""The thin slice end to end offline (D2-3): one research run of slot S04 leaves one
verified, cited fact in Postgres."""

import pytest

from tests.support.thin_slice import (
    EN_QUERY,
    NV_QUERY,
    TRUE_SENTENCE,
    TRUE_STATEMENT,
    URL,
    Slice,
    query_rows,
)

pytestmark = pytest.mark.db


async def test_thin_slice_writes_a_verified_cited_fact(thin_slice: Slice) -> None:
    s = thin_slice
    run = await s.store.runs.run_row(s.run_id)
    assert run is not None
    assert run["status"] == "completed"
    facts = await query_rows(s.store, "SELECT * FROM v_city_facts WHERE city_id = :c", c=s.city_id)
    assert [f["statement"] for f in facts] == [TRUE_STATEMENT]
    fact = facts[0]
    assert fact["url"] == URL
    assert fact["quote"] in TRUE_SENTENCE
    assert fact["verdict"] == "supported"
    assert fact["content_sha256"]
    assert fact["value_as_written"] == "31.5%"
    assert s.search.queries == [EN_QUERY, NV_QUERY]  # the planner's, not the template
