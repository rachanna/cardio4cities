"""One offline research run of slot S04 (D2-3): the real graph, gate, fetcher, parser,
rules and Postgres, with scripted models and a one-page fictional web. Test modules
import the `thin_slice` fixture together with the database fixtures.

The page and the scripted extractor plant three claims: one true statistic, one
statement whose quote is real but whose claim overreaches (the checker refutes it),
and one whose quote is not on the page (code drops it). All content is about the
fictional city Halden Bay, Norvania."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy import text

from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser
from app.adapters.postgres.relational import PostgresRelational
from app.adapters.snapshots.postgres import PostgresSnapshots
from app.domain.vocab import (
    ClaimKind,
    GeographyLevel,
    MeasureType,
    Method,
    Representativeness,
    Sex,
    VerdictLabel,
)
from app.prompts.checker.schema import CheckerOutput, CheckIssue
from app.prompts.extractor.schema import (
    ClaimOut,
    ExtractorOutput,
    LabelsOut,
    PeriodOut,
    PopulationOut,
    StatisticOut,
)
from app.prompts.planner.schema import PlannedQuery, PlannerOutput, SlotQueries
from app.settings import load_settings
from app.workflow.runner import RunManager
from scripts.reference.yaml_reference import read_indicators, read_slots
from tests.support.gazetteer import PLACE, sync_gazetteer
from tests.support.webworld import ALLOW_ALL, Reply, WebWorld
from tests.support.workflow_fakes import (
    HashEmbeddings,
    ListSearch,
    MemoryVector,
    Ports,
    ScriptedLLM,
)

HOST = "health.halden-bay.test"
URL = f"http://{HOST}/heart-survey"  # the local test server speaks plain HTTP
TRUE_SENTENCE = (
    "In the 2024 Halden Bay Heart Survey, 31.5% of adults with hypertension "
    "had their blood pressure under control."
)
OTHER_SENTENCE = "The survey team visited 40 clinics across the coastal districts during spring."
FAR_AWAY = "FAR-AWAY-PARAGRAPH the directorate also published a ferry timetable."
FILLER = "The Norvania Health Directorate thanks every family who took part in the survey. "

TRUE_STATEMENT = "31.5% of adults with hypertension in Halden Bay had it under control in 2024."
PLANTED_STATEMENT = "Halden Bay runs 40 dedicated hypertension control clinics."
MISSING_STATEMENT = "Halden Bay doubled its screening budget."
EN_QUERY = "Halden Bay hypertension control survey"
NV_QUERY = "Halden Bay blodtrykk kontroll"


def page() -> bytes:
    body = f"<p>{TRUE_SENTENCE}</p><p>{OTHER_SENTENCE}</p><p>{FILLER * 20}</p><p>{FAR_AWAY}</p>"
    return (
        "<html><head><title>Halden Bay Heart Survey 2024</title></head><body><main><article>"
        f"<h1>Halden Bay Heart Survey 2024</h1>{body}</article></main></body></html>"
    ).encode()


def labels(measure: MeasureType, period: str | None) -> LabelsOut:
    return LabelsOut(
        geography_level=GeographyLevel.CITY_WIDE, geography_name="Halden Bay",
        measure_type=measure,
        reference_period=PeriodOut(start=period, end=period) if period else None,
        population=PopulationOut(age_min=18, age_max=None, sex=Sex.ALL, group=None),
        setting=None, sample_size=None, case_definition=None, method=Method.MEASURED,
        representativeness=Representativeness.REPRESENTATIVE_SAMPLE,
        denominator_text="adults with hypertension", denominator_stated=True,
    )  # fmt: skip


def extractor(_: str) -> ExtractorOutput:
    return ExtractorOutput(
        claims=[
            ClaimOut(
                slot_id="S04", kind=ClaimKind.STATISTIC, statement=TRUE_STATEMENT,
                quote="31.5% of adults with hypertension had their blood pressure under control",
                quote_lang="en", quote_translation=None,
                labels=labels(MeasureType.CASCADE_CONTROL, "2024"),
                statistic=StatisticOut(indicator_code="HTN_CONTROL", value_as_written="31.5%"),
                relation=None,
            ),
            ClaimOut(  # planted: the quote is real, the statement overreaches (AT-08)
                slot_id="S04", kind=ClaimKind.STATEMENT, statement=PLANTED_STATEMENT,
                quote="The survey team visited 40 clinics across the coastal districts",
                quote_lang="en", quote_translation=None,
                labels=labels(MeasureType.QUALITATIVE, None), statistic=None, relation=None,
            ),
            ClaimOut(  # the quote is not on the page: dropped by code, never checked
                slot_id="S04", kind=ClaimKind.STATEMENT, statement=MISSING_STATEMENT,
                quote="the screening budget was doubled in the last financial year",
                quote_lang="en", quote_translation=None,
                labels=labels(MeasureType.QUALITATIVE, None), statistic=None, relation=None,
            ),
        ]
    )  # fmt: skip


def checker(user: str) -> CheckerOutput:
    if PLANTED_STATEMENT in user:
        return CheckerOutput(
            label=VerdictLabel.REFUTED,
            rationale="The passage says 40 clinics were visited, not that the city runs them.",
            scope_verified=False, period_verified=False, issues=[CheckIssue.CONTRADICTED],
        )  # fmt: skip
    return CheckerOutput(
        label=VerdictLabel.SUPPORTED, rationale="The passage states 31.5% for 2024.",
        scope_verified=True, period_verified=True, issues=[],
    )  # fmt: skip


def planner(_: str) -> PlannerOutput:
    return PlannerOutput(
        slots=[
            SlotQueries(
                slot_id="S04",
                queries=[
                    PlannedQuery(text=EN_QUERY, lang="en", purpose="city survey"),
                    PlannedQuery(text=NV_QUERY, lang="nv", purpose="primary language"),
                ],
            )
        ]
    )


@dataclass
class Slice:
    store: PostgresRelational
    run_id: str
    city_id: str
    anthropic: ScriptedLLM
    openai: ScriptedLLM
    search: ListSearch


@pytest.fixture
async def thin_slice(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> AsyncIterator[Slice]:
    settings = load_settings({**valid_env, "DATABASE_URL": migrated})
    await relational.reference.sync_indicators(read_indicators())
    await relational.reference.sync_slots(read_slots())
    await sync_gazetteer(relational, PLACE)
    anthropic = ScriptedLLM("anthropic", {"planner": planner, "extractor": extractor})
    openai = ScriptedLLM("openai", {"checker": checker})
    search = ListSearch([URL])
    snapshots = PostgresSnapshots(migrated, settings.config.snapshots.max_bytes)
    world = WebWorld()
    world.site(
        HOST, "93.184.216.34", {"/robots.txt": ALLOW_ALL, "/heart-survey": Reply(200, page())}
    )
    with world.running():
        ports = Ports(
            relational=relational, llm={"anthropic": anthropic, "openai": openai},
            search=search, fetch=world.fetcher(), robots=ProtegoRobotsParser(),
            parser=DocumentParser(), embeddings=HashEmbeddings(), vector=MemoryVector(),
            snapshots=snapshots,
        )  # fmt: skip
        manager = RunManager(ports, settings)
        started = await manager.start("9000001", slots=["S04"])
        await manager.wait(started.run_id)
    yield Slice(relational, started.run_id, started.city_id, anthropic, openai, search)
    await snapshots.close()


async def query_rows(store: PostgresRelational, sql: str, **params: Any) -> list[dict[str, Any]]:
    async with store._engine.connect() as conn:
        return [dict(r) for r in (await conn.execute(text(sql), params)).mappings()]
