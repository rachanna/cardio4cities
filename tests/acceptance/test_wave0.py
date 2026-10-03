"""Wave 0 (LLD-2 §13, R-85, BD-13) on real Postgres and Neo4j, with the official APIs
served by a local fictional web (Norvania, XNV). The real collector, pinned fetcher,
adapters, code verification, claim index and graph writes run unchanged.

LLD-2 §13 tests: a supported national claim with the right labels; an altered value
fails the code check; Wave 0 claims never reach the model checker; API calls are gated
(`api_terms:<provider>`, public addresses only); a failure never stops Wave 0."""

import copy
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.graph.graphiti import GraphitiGraph
from app.adapters.parse.documents import DocumentParser
from app.adapters.postgres.relational import PostgresRelational
from app.adapters.snapshots.postgres import PostgresSnapshots
from app.adapters.structured.who_gho import WhoGho
from app.adapters.structured.world_bank import WorldBank
from app.domain.models import CityIdentity
from app.ports.structured import StructuredDataPort
from app.settings import load_settings
from app.workflow.claim_index import claim_point_id
from app.workflow.ids import new_id
from app.workflow.nodes.wave0 import wave0
from app.workflow.rules.crawl_gate import canonicalise
from app.workflow.runner import RunManager
from scripts.reference.yaml_reference import (
    REFERENCE_DIR,
    read_indicators,
    read_slots,
    read_sources,
)
from tests.support.gazetteer import PLACE, sync_gazetteer
from tests.support.thin_slice import query_rows, reachable_graph
from tests.support.webworld import Reply, WebWorld
from tests.support.workflow_fakes import (
    HashEmbeddings,
    ListSearch,
    MemoryVector,
    Ports,
    ScriptedLLM,
)

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "structured"
GHO_HOST, WB_HOST = "ghoapi.norvania.test", "api.worldbank.norvania.test"
GHO_IP, WB_IP = "93.184.216.40", "93.184.216.41"
GHO_BASE, WB_BASE = f"http://{GHO_HOST}/api", f"http://{WB_HOST}/v2"
# value per WHO indicator for the fictional country (both sexes, latest year)
VALUES = {
    "NCD_HYP_PREVALENCE_A": "29.4",
    "NCD_HYP_DIAGNOSIS_A": "52.0",
    "NCD_HYP_TREATMENT_A": "38.7",
    "NCD_HYP_CONTROL_A": "14.8",
    "NCD_DIABETES_PREVALENCE_AGESTD": "11.4",
    "NCDMORT3070": "19.6",
}


def gho_response(code: str) -> bytes:
    """The recorded structure with fictional values for any WHO indicator."""
    if code == "NCD_DIABETES_PREVALENCE_AGESTD":
        return (FIXTURES / "who_gho_NCD_DIABETES_PREVALENCE_AGESTD_XNV.json").read_bytes()
    body = json.loads((FIXTURES / "who_gho_NCD_HYP_CONTROL_A_XNV.json").read_text("utf-8"))
    rows = []
    for row in body["value"]:
        new = copy.deepcopy(row)
        new["IndicatorCode"] = code
        if new["TimeDim"] == 2019 and new["Dim1"] == "SEX_BTSX":
            new["Value"] = f"{VALUES[code]} [9.6-21.2]"
        if code == "NCDMORT3070":
            new.update({"Dim2Type": "AGEGROUP", "Dim2": "AGEGROUP_YEARS30-69"})
        rows.append(new)
    body["value"] = rows
    return json.dumps(body).encode()


def routes() -> tuple[dict[str, Any], dict[str, Any]]:
    gho, wb = WhoGho(GHO_BASE), WorldBank(WB_BASE)
    gho_routes, wb_routes = {}, {}
    for code in VALUES:
        url = canonicalise(gho.request_urls(code, "XNV", {})[0]) or ""
        gho_routes[url.split(GHO_HOST, 1)[1]] = Reply(200, gho_response(code), "application/json")
    url = canonicalise(wb.request_urls("SP.POP.TOTL", "XNV", {})[0]) or ""
    wb_routes[url.split(WB_HOST, 1)[1]] = Reply(
        200, (FIXTURES / "world_bank_SP.POP.TOTL_XNV.json").read_bytes(), "application/json"
    )
    return gho_routes, wb_routes


class AlteringSnapshots:
    """Returns stored bytes with one value changed, as if the record had been tampered with."""

    def __init__(self, inner: PostgresSnapshots, old: bytes, new: bytes) -> None:
        self._inner, self._old, self._new = inner, old, new

    async def put(self, source_id: str, content: bytes, content_type: str) -> Any:
        return await self._inner.put(source_id, content, content_type)

    async def get(self, source_id: str) -> tuple[bytes, str]:
        raw, kind = await self._inner.get(source_id)
        return raw.replace(self._old, self._new), kind


@dataclass
class Wave0Run:
    store: PostgresRelational
    run_id: str
    city: CityIdentity
    result: dict[str, Any]
    models: list[ScriptedLLM]
    world: WebWorld
    vector: MemoryVector
    graph: GraphitiGraph


RunWave0 = Callable[..., Any]


@pytest.fixture
async def run_wave0(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> AsyncIterator[RunWave0]:
    settings = load_settings({**valid_env, "DATABASE_URL": migrated})
    await relational.reference.sync_indicators(read_indicators())
    await relational.reference.sync_slots(read_slots())
    sources = read_sources(REFERENCE_DIR, {i.code for i in read_indicators()})
    await relational.reference.sync_sources(sources.ready)
    await sync_gazetteer(relational, PLACE)
    graph = await reachable_graph()
    snapshots = PostgresSnapshots(migrated, settings.config.snapshots.max_bytes)
    cities: list[str] = []

    async def run(
        gho_ip: str = GHO_IP,
        alter: tuple[bytes, bytes] | None = None,
        structured: dict[str, StructuredDataPort] | None = None,
    ) -> Wave0Run:
        gho_routes, wb_routes = routes()
        world = WebWorld()
        world.site(GHO_HOST, gho_ip, gho_routes)
        world.site(WB_HOST, WB_IP, wb_routes)
        models = [ScriptedLLM("anthropic", {}), ScriptedLLM("openai", {})]
        vector = MemoryVector()
        store_snapshots: Any = AlteringSnapshots(snapshots, *alter) if alter else snapshots
        with world.running():
            ports = Ports(
                relational=relational,
                llm={"anthropic": models[0], "openai": models[1]},
                search=ListSearch([]),
                fetch=world.fetcher(),
                robots=ProtegoRobotsParser(),
                parser=DocumentParser(),
                embeddings=HashEmbeddings(),
                vector=vector,
                snapshots=store_snapshots,
                graph=graph,
                structured=structured
                if structured is not None
                else {"who_gho": WhoGho(GHO_BASE), "world_bank": WorldBank(WB_BASE)},
            )
            place = await relational.reference.place_identity("9000001")
            assert place is not None
            city = CityIdentity(city_id=new_id("city"), admin2_name=None, **place)
            await relational.runs.create_city(city)
            run_id = new_id("run")
            manager = RunManager(ports, settings)
            deps = await manager.build_deps(run_id)
            await relational.runs.create_run(run_id, city.city_id, {}, {})
            await deps.entities.ensure_city(city)
            result = await wave0({"run_id": run_id, "city": city}, {"configurable": {"deps": deps}})
        cities.append(city.city_id)
        return Wave0Run(relational, run_id, city, result, models, world, vector, graph)

    yield run
    for city_id in cities:
        await graph.delete_group(city_id)
    await graph.close()
    await snapshots.close()


async def _claims(r: Wave0Run) -> dict[str, dict[str, Any]]:
    rows = await query_rows(
        r.store,
        "SELECT c.*, s.indicator_code, s.value_as_written, s.unit, v.label AS verdict,"
        " v.verifier_model, v.verifier_family, v.rationale, src.kind AS source_kind,"
        " src.parsed_text, src.publisher_class FROM claim c"
        " JOIN statistic s USING (claim_id) JOIN verdict v USING (claim_id)"
        " JOIN source src ON src.source_id = c.source_id WHERE c.run_id = :r",
        r=r.run_id,
    )
    return {row["indicator_code"]: row for row in rows}


async def test_a_supported_national_claim_with_the_registry_labels(run_wave0: RunWave0) -> None:
    r: Wave0Run = await run_wave0()
    claims = await _claims(r)
    assert sorted(claims) == sorted(
        ["HTN_PREV", "HTN_AWARE", "HTN_TREATED", "HTN_CONTROL", "DM_PREV", "NCD_PREMATURE_MORT"]
    )
    c = claims["HTN_CONTROL"]
    line = "NCD_HYP_CONTROL_A | XNV | 2019 | SEX_BTSX | 30-79 | 14.8 [9.6-21.2]"
    assert (c["status"], c["verdict"]) == ("supported", "supported")
    assert (c["verifier_model"], c["verifier_family"]) == ("code:record_match", "code")
    assert (c["slot_id"], c["quote"], c["parsed_text"]) == ("S04", line, line)
    assert (c["value_as_written"], c["unit"]) == ("14.8", "%")
    assert (c["geography_level"], c["geography_name"]) == ("national", "Norvania")
    assert (c["measure_type"], c["representativeness"]) == ("cascade_control", "modelled")
    assert str(c["reference_start"]) == "2019-01-01"
    assert str(c["reference_end"]) == "2019-12-31"
    opt = c["optional_labels"]
    assert (opt["population_age_min"], opt["population_age_max"]) == (30, 79)
    assert (opt["method"], opt["threshold_code"]) == ("modelled", "bp_140_90")
    assert opt["denominator_text"] == "adults aged 30-79 with hypertension"
    assert (c["source_kind"], c["publisher_class"]) == ("structured_api", "multilateral")
    assert claims["DM_PREV"]["quote"].endswith("| 18+ | 11.4 [8.2-15.1]")
    assert len(r.result["wave0_claim_ids"]) == 6


async def test_wave0_claims_never_reach_the_model_checker(run_wave0: RunWave0) -> None:
    r: Wave0Run = await run_wave0()
    assert all(model.calls == [] for model in r.models)


async def test_api_calls_are_gated_under_api_terms_without_robots(run_wave0: RunWave0) -> None:
    r: Wave0Run = await run_wave0()
    decisions = await query_rows(
        r.store, "SELECT domain, outcome, rule FROM crawl_decision WHERE run_id = :r", r=r.run_id
    )
    assert len(decisions) == 7  # six WHO indicators and population
    assert {(d["outcome"], d["rule"]) for d in decisions if d["domain"] == GHO_HOST} == {
        ("allowed", "api_terms:who_gho")
    }
    assert {d["rule"] for d in decisions if d["domain"] == WB_HOST} == {"api_terms:world_bank"}
    assert "/robots.txt" not in r.world.paths(GHO_HOST)  # the API's terms govern, not robots


async def test_population_is_stored_as_a_source_without_a_claim(run_wave0: RunWave0) -> None:
    r: Wave0Run = await run_wave0()
    rows = await query_rows(
        r.store,
        "SELECT parsed_text FROM source WHERE run_id = :r AND domain = :d",
        r=r.run_id,
        d=WB_HOST,
    )
    assert [row["parsed_text"] for row in rows] == [
        "SP.POP.TOTL | XNV | 2025 | total | all ages | 5123456"
    ]


async def test_findings_are_indexed_streamed_and_linked_in_the_graph(run_wave0: RunWave0) -> None:
    r: Wave0Run = await run_wave0()
    claims = await _claims(r)
    events = await r.store.runs.events_after(r.run_id, 0)
    findings = [e["payload"] for e in events if e["type"] == "wave0_finding"]
    assert len(findings) == 6
    assert all(f["status"] == "supported" and f["graph_edge"] for f in findings)
    (collection,) = [n for n in r.vector.points if n.startswith("claim_index__")]
    indexed = {p.id for p in r.vector.points[collection]}
    assert {claim_point_id(c["claim_id"]) for c in claims.values()} <= indexed
    edges = await r.graph.search_edges(r.city.city_id, ["MEASURED_IN"])
    assert {h.edge.attributes["claim_ids"][0] for h in edges} == {
        c["claim_id"] for c in claims.values()
    }
    assert {h.object.name for h in edges} == {"Norvania"}


async def test_an_altered_value_fails_the_code_check(run_wave0: RunWave0) -> None:
    """LLD-2 §13: the record re-read from the snapshot must equal the claim."""
    r: Wave0Run = await run_wave0(alter=(b'"14.8 [9.6-21.2]"', b'"41.8 [9.6-21.2]"'))
    c = (await _claims(r))["HTN_CONTROL"]
    assert (c["status"], c["verdict"]) == ("insufficient", "insufficient")
    assert c["verifier_family"] == "code"
    facts = await query_rows(
        r.store,
        "SELECT claim_id FROM v_fact_evidence WHERE claim_id = :c "
        "AND status IN ('supported','contested')",
        c=c["claim_id"],
    )
    assert facts == []
    (collection,) = [n for n in r.vector.points if n.startswith("claim_index__")]
    assert claim_point_id(c["claim_id"]) not in {p.id for p in r.vector.points[collection]}


async def test_an_api_host_on_a_private_address_is_refused(run_wave0: RunWave0) -> None:
    r: Wave0Run = await run_wave0(gho_ip="10.0.0.7")
    decisions = await query_rows(
        r.store,
        "SELECT outcome, rule FROM crawl_decision WHERE run_id = :r AND domain = :d",
        r=r.run_id,
        d=GHO_HOST,
    )
    assert {(d["outcome"], d["rule"]) for d in decisions} == {
        ("blocked_private_address", "api_terms:who_gho")
    }
    assert r.world.paths(GHO_HOST) == []  # no request was made
    assert await _claims(r) == {}
    sources = await query_rows(r.store, "SELECT domain FROM source WHERE run_id = :r", r=r.run_id)
    assert [s["domain"] for s in sources] == [WB_HOST]  # the other provider still ran


class BrokenAdapter:
    provider = "who_gho"

    def request_urls(self, code: str, country_iso3: str, params: Any) -> list[str]:
        raise RuntimeError("provider changed its API")

    def parse(self, code: str, raw: bytes) -> list[Any]:
        raise RuntimeError("unused")


async def test_a_wave0_failure_never_stops_the_run(run_wave0: RunWave0) -> None:
    r: Wave0Run = await run_wave0(
        structured={"who_gho": BrokenAdapter(), "world_bank": WorldBank(WB_BASE)}
    )
    assert r.result == {"wave0_claim_ids": []}
    sources = await query_rows(r.store, "SELECT domain FROM source WHERE run_id = :r", r=r.run_id)
    assert [s["domain"] for s in sources] == [WB_HOST]
