"""The thin slice end to end offline (D2-3, BD-10): one research run of slot S04 leaves
verified, cited facts in Postgres; a figure for a nearby place is kept as wider-area
evidence and one for a distant place is dropped."""

from typing import Any

import pytest

from tests.support.thin_slice import (
    ELSEWHERE_STATEMENT,
    EN_GOV_QUERY,
    EN_QUERY,
    METHODS,
    NEARBY_STATEMENT,
    NEW_GOV_STATEMENT,
    NV_GOV_QUERY,
    NV_QUERY,
    TRUE_SENTENCE,
    TRUE_STATEMENT,
    URL,
    Slice,
    query_rows,
)

pytestmark = pytest.mark.db


async def _facts(s: Slice) -> dict[str, dict[str, Any]]:
    rows = await query_rows(s.store, "SELECT * FROM v_city_facts WHERE city_id = :c", c=s.city_id)
    return {str(r["statement"]): r for r in rows}


async def test_thin_slice_writes_verified_cited_facts(thin_slice: Slice) -> None:
    s = thin_slice
    run = await s.store.runs.run_row(s.run_id)
    assert run is not None
    assert run["status"] == "completed"
    facts = await _facts(s)
    assert sorted(facts) == sorted([TRUE_STATEMENT, NEARBY_STATEMENT, NEW_GOV_STATEMENT])
    fact = facts[TRUE_STATEMENT]
    assert fact["url"] == URL
    assert fact["quote"] in TRUE_SENTENCE
    assert fact["verdict"] == "supported"
    assert fact["content_sha256"]
    assert fact["value_as_written"] == "31.5%"
    assert fact["geography_fit"] == {
        "relation": "city",
        "place_name": "Halden Bay",
        "distance_km": 0,
    }
    planned = [EN_QUERY, NV_QUERY, EN_GOV_QUERY, NV_GOV_QUERY]
    assert sorted(s.search.queries) == sorted(planned)  # the planner's, not the template


async def test_period_stated_far_from_the_quote_is_kept_with_its_located_passage(
    thin_slice: Slice,
) -> None:
    """BD-10: the label quote is located exactly, so the period label stands."""
    fact = (await _facts(thin_slice))[TRUE_STATEMENT]
    assert str(fact["reference_end"]) == "2024-12-31"
    assert "period_not_stated" not in fact["flags"]
    rows = await query_rows(
        thin_slice.store, "SELECT parsed_text FROM source WHERE url = :u", u=URL
    )
    start, end = fact["label_spans"]["period"]
    assert rows[0]["parsed_text"][start:end] in METHODS


async def test_nearby_place_is_kept_as_wider_area_and_unlocated_period_cleared(
    thin_slice: Slice,
) -> None:
    """BD-10: a place within geography.nearby_km answers for the city as wider-area
    evidence; its period quote lacks the labelled year, so the period is cleared."""
    fact = (await _facts(thin_slice))[NEARBY_STATEMENT]
    fit = fact["geography_fit"]
    assert fit["relation"] == "nearby"
    assert fit["place_name"] == "Kestrel Point"
    assert 20 <= fit["distance_km"] <= 35
    assert fact["period_type"] == "publication_date_proxy"
    assert "period_not_stated" in fact["flags"]
    assert fact["label_spans"] == {}


async def test_distant_place_is_dropped_before_checking(thin_slice: Slice) -> None:
    """BD-10: a place beyond geography.nearby_km never answers for the city."""
    events = await thin_slice.store.runs.events_after(thin_slice.run_id, 0)
    dropped = {
        e["payload"]["statement"]: e["payload"] for e in events if e["type"] == "claim_dropped"
    }
    drop = dropped[ELSEWHERE_STATEMENT]
    assert drop["reason"] == "geography_elsewhere"
    assert drop["place"] == "Port Ostra"
    assert drop["distance_km"] > 75
    assert all(ELSEWHERE_STATEMENT not in c.user for c in thin_slice.openai.calls)
