"""Graph and retrieval indexes on an offline research run (D2-4; BD-11; CHG-01).

D2-4 "Done when": a GOVERNS edge is written and readable with its claim ID; the newer
GOVERNS claim supersedes the older one, whose edge is end-dated and kept; an acronym
resolves to the same entity as its long form (AT-26 end to end); a refuted claim has no
claim-index point (AT-39 plumbing); `search_tsv` matches acronyms and numbers exactly.
"""

from datetime import date

import pytest

from app.workflow.claim_index import claim_point_id
from tests.support.thin_slice import (
    NEW_GOV_STATEMENT,
    OLD_GOV_STATEMENT,
    PLANTED_STATEMENT,
    TRUE_STATEMENT,
    Slice,
    query_rows,
)

pytestmark = pytest.mark.db


async def _claim_ids(s: Slice) -> dict[str, str]:
    rows = await query_rows(
        s.store, "SELECT statement, claim_id FROM claim WHERE run_id = :r", r=s.run_id
    )
    return {r["statement"]: r["claim_id"] for r in rows}


async def test_governs_edge_is_written_and_readable_with_its_claim_id(thin_slice: Slice) -> None:
    s = thin_slice
    ids = await _claim_ids(s)
    (hit,) = await s.graph.search_edges(s.city_id, ["GOVERNS"])  # current edges only
    assert hit.edge.attributes["claim_ids"] == [ids[NEW_GOV_STATEMENT]]
    assert hit.edge.valid_at == date(2024, 4, 1)
    assert (hit.subject.name, hit.object.name) == ("Halden Bay Health Office", "Halden Bay")
    links = await query_rows(
        s.store,
        "SELECT edge_uuid::text AS e FROM graph_link WHERE claim_id = :c",
        c=ids[NEW_GOV_STATEMENT],
    )
    assert [r["e"] for r in links] == [hit.edge.uuid]


async def test_older_governs_edge_is_end_dated_not_deleted(thin_slice: Slice) -> None:
    s = thin_slice
    ids = await _claim_ids(s)
    every = await s.graph.search_edges(s.city_id, ["GOVERNS"], include_ended=True)
    by_claim = {h.edge.attributes["claim_ids"][0]: h.edge for h in every}
    old = by_claim[ids[OLD_GOV_STATEMENT]]
    assert old.invalid_at == date(2024, 3, 31)  # the source's own end date ("until March 2024")
    status = await query_rows(
        s.store, "SELECT status FROM claim WHERE claim_id = :c", c=ids[OLD_GOV_STATEMENT]
    )
    assert status[0]["status"] == "superseded"
    as_of = await s.graph.search_edges(s.city_id, ["GOVERNS"], as_of=date(2023, 6, 30))
    assert [h.edge.uuid for h in as_of] == [old.uuid]


async def test_acronym_and_long_form_are_one_entity(thin_slice: Slice) -> None:
    """AT-26 end to end: "HBHO" is defined in the source as the Halden Bay Health Office."""
    rows = await query_rows(
        thin_slice.store,
        "SELECT a.surface_form, a.method, e.canonical_name FROM entity_alias a"
        " JOIN entity e USING (entity_id) WHERE a.city_id = :c AND e.entity_type = 'Organization'",
        c=thin_slice.city_id,
    )
    names = {r["surface_form"]: r["canonical_name"] for r in rows}
    assert names["HBHO"] == names["Halden Bay Health Office"] == "Halden Bay Health Office"
    assert {r["method"] for r in rows if r["surface_form"] == "HBHO"} == {"acronym"}


async def test_claim_index_holds_only_supported_or_contested_claims(thin_slice: Slice) -> None:
    """AT-39 plumbing: refuted and superseded claims have no point; supported ones do."""
    s = thin_slice
    ids = await _claim_ids(s)
    (collection,) = [n for n in s.vector.points if n.startswith("claim_index__")]
    points = {p.id: p.payload for p in s.vector.points[collection]}
    assert claim_point_id(ids[TRUE_STATEMENT]) in points
    assert claim_point_id(ids[NEW_GOV_STATEMENT]) in points
    assert claim_point_id(ids[PLANTED_STATEMENT]) not in points
    assert claim_point_id(ids[OLD_GOV_STATEMENT]) not in points
    payload = points[claim_point_id(ids[TRUE_STATEMENT])]
    assert payload["status"] == "supported"
    assert payload["indicator_code"] == "HTN_CONTROL"
    assert payload["city_id"] == s.city_id


@pytest.mark.parametrize(
    ("term", "statement"), [("HBHO", NEW_GOV_STATEMENT), ("31.5", TRUE_STATEMENT)]
)
async def test_keyword_index_matches_acronyms_and_numbers_exactly(
    thin_slice: Slice, term: str, statement: str
) -> None:
    rows = await query_rows(
        thin_slice.store,
        "SELECT statement FROM claim WHERE run_id = :r"
        " AND search_tsv @@ websearch_to_tsquery('simple', :q)",
        r=thin_slice.run_id,
        q=term,
    )
    assert statement in [r["statement"] for r in rows]
