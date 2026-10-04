"""The research views and contested pairs against Postgres (code review RV-110):
v_city_facts shows only claims of the city's latest finished run that are supported or
contested and carry a supported verdict; a contested pair is stored once however often the
consistency rule records it. Fictional city."""

from typing import Any

import pytest
from sqlalchemy import text

from app.domain.ids import graph_uuid

pytestmark = pytest.mark.db

SEED = (
    "INSERT INTO ref_country (iso2, iso3, name) VALUES ('XN', 'XNV', 'Norvania')",
    "INSERT INTO ref_place (gazetteer_id, name, ascii_name, country_iso2, lat, lon)"
    " VALUES ('9000001', 'Halden Bay', 'Halden Bay', 'XN', 60.1, 5.2)",
    "INSERT INTO ref_slot (slot_id, dimension, question, short_label, answer_kind,"
    " accepted_levels) VALUES ('S03', 'D2', 'q', 'l', 'statistic', '{city_wide}')",
    "INSERT INTO city (city_id, gazetteer_id, identity) VALUES ('city_hb', '9000001', '{}')",
)
SOURCE = (
    "INSERT INTO source (source_id, run_id, url, url_canonical, domain, kind, publisher_class,"
    " retrieved_at, found_via) VALUES (:s, :r, 'https://h.test/a', 'https://h.test/a',"
    " 'h.test', 'web_html', 'government', now(), 'x')"
)
CLAIM = (
    "INSERT INTO claim (claim_id, run_id, city_id, slot_id, source_id, kind, statement, quote,"
    " quote_lang, span_start, span_end, geography_level, geography_name, measure_type,"
    " period_type, representativeness, status, extractor_model, prompt_version) VALUES"
    " (:c, :r, 'city_hb', 'S03', :s, 'statistic', 'x', 'q', 'en', 0, 1, 'city_wide',"
    " 'Halden Bay', 'measured_prevalence', 'period', 'census', :st, 'm', 'v')"
)
VERDICT = (
    "INSERT INTO verdict (claim_id, label, rationale, scope_verified, period_verified,"
    " verifier_model, verifier_family, prompt_version)"
    " VALUES (:c, :v, 'r', true, true, 'm', 'openai', 'v')"
)
# Each status with the verdict that led to it; an extracted claim has none yet
VERDICTS = {
    "supported": "supported",
    "contested": "supported",
    "superseded": "supported",
    "refuted": "refuted",
    "insufficient": "insufficient",
    "extracted": None,
}


async def _run(relational: Any, run: str, status: str) -> None:
    await relational.runs.create_run(run, "city_hb", {}, {})
    async with relational._engine.begin() as conn:
        await conn.execute(text(SOURCE), {"s": f"src_{run}", "r": run})
        for claim_status, verdict in VERDICTS.items():
            claim_id = f"clm_{run}_{claim_status}"
            await conn.execute(
                text(CLAIM), {"c": claim_id, "r": run, "s": f"src_{run}", "st": claim_status}
            )
            if verdict:
                await conn.execute(text(VERDICT), {"c": claim_id, "v": verdict})
    await relational.runs.set_status(run, status)


async def _rows(relational: Any, sql: str) -> list[Any]:
    async with relational._engine.connect() as conn:
        return list((await conn.execute(text(sql))).scalars().all())


async def test_city_facts_show_the_latest_run_and_showable_claims_only(relational: Any) -> None:
    async with relational._engine.begin() as conn:
        for sql in SEED:
            await conn.execute(text(sql))
    await _run(relational, "run_1", "completed")
    await _run(relational, "run_2", "completed")
    await _run(relational, "run_3", "running")  # in progress: changes nothing shown

    shown = await _rows(relational, "SELECT claim_id FROM v_city_facts ORDER BY 1")

    assert shown == ["clm_run_2_contested", "clm_run_2_supported"]


async def test_a_contested_pair_is_stored_once(relational: Any) -> None:
    async with relational._engine.begin() as conn:
        for sql in SEED:
            await conn.execute(text(sql))
    await _run(relational, "run_1", "completed")
    for _ in range(2):  # recorded again, as on a resumed run: still one pair
        await relational.research.add_contested_pair(
            "cp_1", "clm_run_1_contested", "clm_run_1_supported", "clm_run_1_supported", "r"
        )

    pairs = await _rows(relational, "SELECT headline_claim FROM contested_pair")

    assert pairs == ["clm_run_1_supported"]


async def test_purging_the_graph_clears_every_graph_link(relational: Any) -> None:
    """RV-094: after `poe purge-graph` no link points at an edge that no longer exists."""
    async with relational._engine.begin() as conn:
        for sql in SEED:
            await conn.execute(text(sql))
    await _run(relational, "run_1", "completed")
    await relational.research.add_graph_link(
        "clm_run_1_supported", graph_uuid("clm_run_1_supported")
    )
    await relational.research.add_graph_link(
        "clm_run_1_contested", graph_uuid("clm_run_1_contested")
    )

    assert await relational.research.clear_graph_links() == 2
    assert await relational.research.graph_link("clm_run_1_supported") is None
    assert await relational.research.clear_graph_links() == 0
