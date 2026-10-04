"""The read API on a researched city (D3-1; LLD-4 §3.2-3.3): AT-12, AT-25, AT-27, AT-37,
and AT-13/AT-14 for findings. The app reads the thin slice's real stores (Postgres and the
Neo4j graph), offline; the fictional city is Halden Bay, Norvania."""

import time
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest

from app.adapters.postgres.relational import PostgresRelational
from app.api.auth import COOKIE_NAME, AccessConfig, issue_token
from app.container import Container
from app.main import create_app
from tests.support.thin_slice import (
    GOV_URL,
    NEARBY_STATEMENT,
    NEW_GOV_STATEMENT,
    TRUE_SENTENCE,
    TRUE_STATEMENT,
    URL,
    Slice,
    query_rows,
    run_slice,
)

pytestmark = [pytest.mark.db, pytest.mark.stores]
SECRET = "read-api-test-secret-0123456789"  # noqa: S105 - signs test sessions only


@pytest.fixture
async def api(thin_slice: Slice) -> AsyncIterator[httpx.AsyncClient]:
    """A signed-in client on an app wired to the slice's stores (no lifespan: the slice's
    adapters are used as they are)."""
    assert thin_slice.ports is not None
    app = create_app(env_file=None)
    app.state.container = Container(
        settings=thin_slice.settings,
        relational=thin_slice.store,
        graph=thin_slice.graph,
        snapshots=thin_slice.ports.snapshots,
    )
    app.state.access = AccessConfig("a" * 12, "b" * 12, SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        client.cookies.set(COOKIE_NAME, issue_token("viewer", SECRET))
        yield client


async def get(api: httpx.AsyncClient, path: str, **params: Any) -> Any:
    response = await api.get(f"/api/v1{path}", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def card_for(items: list[dict[str, Any]], statement: str) -> dict[str, Any]:
    return next(c for c in items if c["statement"] == statement)


# --- "Open existing" and the brief (AT-25, AT-37) ----------------------------------------


async def test_open_existing_lists_the_city_with_its_run_date(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    """AT-37, AT-25: a researched city opens from storage, with the date of its run."""
    body = await get(api, "/cities")
    (item,) = body["items"]
    assert item["city_id"] == thin_slice.city_id
    assert (item["name"], item["country_name"]) == ("Halden Bay", "Norvania")
    assert item["latest_run_id"] == thin_slice.run_id
    assert item["latest_run_status"] == "completed"
    assert item["latest_run_at"]
    assert body["next_cursor"] is None


async def test_the_brief_is_read_from_storage_without_a_new_run(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    """AT-25: knowledge available without re-running; the run date is shown."""
    searched = len(thin_slice.search.queries)
    body = await get(api, f"/cities/{thin_slice.city_id}/brief")
    assert len(thin_slice.search.queries) == searched  # nothing researched again
    assert body["run"]["run_id"] == thin_slice.run_id
    assert body["run"]["finished_at"]
    assert body["city"]["name"] == "Halden Bay"
    assert {r["slot_id"]: r["status_word"] for r in body["coverage"]} == {
        "S01": "Answered", "S04": "Answered",
    }  # fmt: skip
    summarised = [c for cards in body["summary"].values() for c in cards]
    assert summarised  # High or Medium facts only (HD-08)
    assert all(c["confidence"]["label"] in ("high", "medium") for c in summarised)
    assert body["counts"]["claims"]["supported"] == 3


async def test_an_unknown_city_is_not_found(api: httpx.AsyncClient) -> None:
    response = await api.get("/api/v1/cities/city_unknown/brief")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


async def test_reading_needs_a_session(api: httpx.AsyncClient, thin_slice: Slice) -> None:
    api.cookies.clear()
    for path in ("/cities", f"/cities/{thin_slice.city_id}/brief", "/facts/clm_x/evidence"):
        assert (await api.get(f"/api/v1{path}")).status_code == 401


# --- findings (AT-13, AT-14) ---------------------------------------------------------------


async def test_findings_are_fact_cards_of_confirmed_claims_only(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    body = await get(api, f"/cities/{thin_slice.city_id}/findings")
    statements = {c["statement"] for c in body["items"]}
    assert statements == {TRUE_STATEMENT, NEARBY_STATEMENT, NEW_GOV_STATEMENT}
    card = card_for(body["items"], TRUE_STATEMENT)
    assert card["status_word"] == "Confirmed"
    assert card["value_as_written"] == "31.5%"
    assert card["geography"] == {
        "level": "city_wide",
        "level_word": "city-wide",
        "name": "Halden Bay",
    }
    assert card["source"]["url"] == URL
    assert card["confidence"]["reasons"]


async def test_a_wider_area_figure_is_flagged_with_its_population_and_period(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    """AT-13's flag: a figure for another place carries the 'Not city-level' badge, with
    its population and reference period (here not stated by the source, so flagged)."""
    body = await get(api, f"/cities/{thin_slice.city_id}/findings", slot="S04")
    card = card_for(body["items"], NEARBY_STATEMENT)
    assert card["main_badge"] == {"code": "not_city_level", "label": "Not city-level"}
    assert set(card["population"]) == {"age_min", "age_max", "sex", "group", "subgroup"}
    assert card["period"]["stated"] is False
    assert [r["slot_id"] for r in body["slots"]] == ["S04"]


async def test_findings_filter_by_badge_and_dimension(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    flagged = await get(api, f"/cities/{thin_slice.city_id}/findings", badge="not_city_level")
    assert [c["statement"] for c in flagged["items"]] == [NEARBY_STATEMENT]
    none = await get(api, f"/cities/{thin_slice.city_id}/findings", dimension="D6")
    assert none["items"] == []


async def test_findings_page_with_an_opaque_cursor(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    first = await get(api, f"/cities/{thin_slice.city_id}/findings", limit=2)
    assert len(first["items"]) == 2
    rest = await get(
        api, f"/cities/{thin_slice.city_id}/findings", limit=2, cursor=first["next_cursor"]
    )
    assert len(rest["items"]) == 1
    assert rest["next_cursor"] is None
    bad = await api.get(f"/api/v1/cities/{thin_slice.city_id}/findings", params={"cursor": "%%"})
    assert bad.status_code == 400


# --- evidence and snapshots (AT-12, AT-27) --------------------------------------------------


async def _claim_id(thin_slice: Slice, statement: str) -> str:
    (row,) = await query_rows(
        thin_slice.store, "SELECT claim_id FROM claim WHERE run_id = :r AND statement = :s",
        r=thin_slice.run_id, s=statement,
    )  # fmt: skip
    return str(row["claim_id"])


async def test_evidence_resolves_a_fact_to_its_full_provenance(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    """AT-12: URL, publisher, publication and retrieval dates, verbatim passage, geography
    level and verdict, plus the snapshot."""
    claim_id = await _claim_id(thin_slice, TRUE_STATEMENT)
    body = await get(api, f"/facts/{claim_id}/evidence")
    card = body["card"]
    assert card["source"]["url"] == URL
    assert card["source"]["publisher_class"]
    assert card["source"]["retrieved_at"]
    assert "published_date" in card["source"]
    assert card["geography"]["level"] == "city_wide"
    passage = body["passage"]
    quote = passage["text"][passage["highlight_start"] : passage["highlight_end"]]
    assert quote == body["quote"]
    assert quote in TRUE_SENTENCE
    assert body["verdict"]["label"] == "supported"
    assert body["verdict"]["rationale"]
    assert body["label_passages"]["period"]  # the period stated far from the quote (BD-10)
    assert body["snapshot"]["sha256"]
    assert body["snapshot"]["url"] == f"/api/v1/snapshots/{card['source']['source_id']}"


async def test_a_rejected_claim_shows_as_reported_not_confirmed(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    """LLD-4 §3.3: rejected claims stay inspectable (DS-3), never as facts."""
    (row,) = await query_rows(
        thin_slice.store, "SELECT claim_id FROM claim WHERE run_id = :r AND status = 'refuted'",
        r=thin_slice.run_id,
    )  # fmt: skip
    body = await get(api, f"/facts/{row['claim_id']}/evidence")
    assert body["card"]["status_word"] == "Reported, not confirmed"
    assert body["card"]["confidence"] is None
    assert body["verdict"]["label"] == "refuted"


async def test_the_snapshot_is_the_page_as_retrieved(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    """AT-27: the preserved bytes, whatever the live page says now."""
    claim_id = await _claim_id(thin_slice, TRUE_STATEMENT)
    evidence = await get(api, f"/facts/{claim_id}/evidence")
    assert thin_slice.world is not None
    thin_slice.world.sites["health.halden-bay.test"]["/heart-survey"] = None  # type: ignore[assignment]
    response = await api.get(evidence["snapshot"]["url"])
    assert response.status_code == 200
    assert response.headers["x-snapshot-sha256"] == evidence["snapshot"]["sha256"]
    assert TRUE_SENTENCE.encode() in response.content
    assert "sandbox" in response.headers["content-security-policy"]
    missing = await api.get("/api/v1/snapshots/src_missing")
    assert missing.status_code == 404


# --- entities: the knowledge graph, checked again in Postgres ------------------------------


async def test_entities_and_an_entity_page_read_the_graph(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    body = await get(api, f"/cities/{thin_slice.city_id}/entities")
    named = {e["name"]: e for group in body["by_type"].values() for e in group}
    assert named  # entities named by confirmed relation facts
    office = next(e for n, e in named.items() if n != "Halden Bay")
    page = await get(api, f"/cities/{thin_slice.city_id}/entities/{office['entity_id']}")
    assert page["graph_used"] is True
    assert page["edges"]
    edge = page["edges"][0]
    assert edge["relation"] == "GOVERNS"
    assert edge["status"] == "current"
    new_gov = await _claim_id(thin_slice, NEW_GOV_STATEMENT)
    assert new_gov in edge["claim_ids"]
    assert GOV_URL  # the governance page these come from


async def test_an_entity_of_another_city_is_not_found(
    api: httpx.AsyncClient, thin_slice: Slice
) -> None:
    response = await api.get(f"/api/v1/cities/{thin_slice.city_id}/entities/ent_missing")
    assert response.status_code == 404


async def test_researching_a_stored_city_again_starts_a_new_live_run(
    api: httpx.AsyncClient,
    thin_slice: Slice,
    relational: PostgresRelational,
    migrated: str,
    valid_env: dict[str, str],
) -> None:
    """AT-37: "Research" on a city in storage runs again, live: a new run of the same city
    whose requests come after it was asked for; "Open existing" then shows the new run."""
    requested = time.monotonic()
    async with run_slice(relational, migrated, valid_env) as again:
        assert again.city_id == thin_slice.city_id
        assert again.run_id != thin_slice.run_id
        assert again.world is not None
        assert again.world.log
        assert all(hit.at >= requested for hit in again.world.log)
        (item,) = (await get(api, "/cities"))["items"]
        assert item["latest_run_id"] == again.run_id


async def test_the_sixteen_slots_are_listed_for_the_coverage_grid(api: httpx.AsyncClient) -> None:
    """D3-4 (BD-41): the live grid names every slot before the run reports on it."""
    slots = await get(api, "/slots")
    assert [s["slot_id"] for s in slots] == [f"S{n:02d}" for n in range(1, 17)]
    assert [s["slot_id"] for s in slots if s["headline"]] == ["S04"]
