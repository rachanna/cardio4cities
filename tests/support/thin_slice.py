"""One offline research run of slot S04 (D2-3, BD-10): the real graph, gate, fetcher,
parser, rules and Postgres, with scripted models and a one-page fictional web. Test
modules import the `thin_slice` fixture together with the database fixtures.

The page and the scripted extractor plant five claims: a true statistic whose period is
stated in the methods, far from the quote (a label quote); a statement whose quote is
real but whose claim overreaches (the checker refutes it); a quote that is not on the
page (dropped); a figure for a nearby town (kept, Not city-level) whose period label
quote does not hold the labelled year (period cleared); and a figure for a town beyond
`geography.nearby_km` (dropped). All content is about the fictional Halden Bay, Norvania."""

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
    LabelQuotesOut,
    LabelsOut,
    PeriodOut,
    PopulationOut,
    StatisticOut,
)
from app.prompts.planner.schema import PlannedQuery, PlannerOutput, SlotQueries
from app.settings import load_settings
from app.workflow.runner import RunManager
from scripts.reference.yaml_reference import read_indicators, read_slots
from tests.support.gazetteer import NEAR_TOWN, PLACE, TOWN, sync_gazetteer
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
    "In the Halden Bay Heart Survey, 31.5% of adults with hypertension "
    "had their blood pressure under control."
)
OTHER_SENTENCE = "The survey team visited 40 clinics across the coastal districts during spring."
NEARBY_SENTENCE = (
    "In neighbouring Kestrel Point, 27.0% of adults with hypertension had it controlled."
)
ELSEWHERE_SENTENCE = "In distant Port Ostra, 19.0% of adults with hypertension had it controlled."
METHODS = (
    "Methods: the Halden Bay Heart Survey interviewed adults aged 18 and over in their homes "
    "between March and October 2024."
)
FAR_AWAY = "FAR-AWAY-PARAGRAPH the directorate also published a ferry timetable."
FILLER = "The Norvania Health Directorate thanks every family who took part in the survey. "

TRUE_STATEMENT = "31.5% of adults with hypertension in Halden Bay had it under control in 2024."
PLANTED_STATEMENT = "Halden Bay runs 40 dedicated hypertension control clinics."
MISSING_STATEMENT = "Halden Bay doubled its screening budget."
NEARBY_STATEMENT = "27.0% of adults with hypertension in Kestrel Point had it controlled in 2023."
ELSEWHERE_STATEMENT = "19.0% of adults with hypertension in Port Ostra had it controlled."
PERIOD_QUOTE = (
    "the Halden Bay Heart Survey interviewed adults aged 18 and over in their homes "
    "between March and October 2024"
)
EN_QUERY = "Halden Bay hypertension control survey"
NV_QUERY = "Halden Bay blodtrykk kontroll"


def page() -> bytes:
    body = (
        f"<p>{TRUE_SENTENCE}</p><p>{OTHER_SENTENCE}</p><p>{NEARBY_SENTENCE}</p>"
        f"<p>{ELSEWHERE_SENTENCE}</p><p>{FILLER * 20}</p><p>{METHODS}</p>"
        f"<p>{FILLER * 10}</p><p>{FAR_AWAY}</p>"
    )
    return (
        "<html><head><title>Halden Bay Heart Survey</title></head><body><main><article>"
        f"<h1>Halden Bay Heart Survey</h1>{body}</article></main></body></html>"
    ).encode()


def labels(measure: MeasureType, period: str | None, place: str = "Halden Bay") -> LabelsOut:
    return LabelsOut(
        geography_level=GeographyLevel.CITY_WIDE, geography_name=place,
        measure_type=measure,
        reference_period=PeriodOut(start=period, end=period) if period else None,
        population=PopulationOut(age_min=18, age_max=None, sex=Sex.ALL, group=None),
        setting=None, sample_size=None, case_definition=None, method=Method.MEASURED,
        representativeness=Representativeness.REPRESENTATIVE_SAMPLE,
        denominator_text="adults with hypertension", denominator_stated=True,
    )  # fmt: skip


def statistic(value: str) -> StatisticOut:
    return StatisticOut(indicator_code="HTN_CONTROL", value_as_written=value)


def claim(statement: str, quote: str, **fields: Any) -> ClaimOut:
    values: dict[str, Any] = {
        "slot_id": "S04", "kind": ClaimKind.STATEMENT, "statement": statement, "quote": quote,
        "quote_lang": "en", "quote_translation": None, "statistic": None, "relation": None,
        "label_quotes": None, "labels": labels(MeasureType.QUALITATIVE, None),
    }  # fmt: skip
    values.update(fields)
    return ClaimOut(**values)


def extractor(_: str) -> ExtractorOutput:
    control = MeasureType.CASCADE_CONTROL
    period_quote = LabelQuotesOut(period=PERIOD_QUOTE, geography=None, population=None)
    return ExtractorOutput(
        claims=[
            claim(  # true; its period is stated in the methods, far from the quote
                TRUE_STATEMENT,
                "31.5% of adults with hypertension had their blood pressure under control",
                kind=ClaimKind.STATISTIC, labels=labels(control, "2024"),
                statistic=statistic("31.5%"), label_quotes=period_quote,
            ),
            claim(  # planted: the quote is real, the statement overreaches (AT-08)
                PLANTED_STATEMENT,
                "The survey team visited 40 clinics across the coastal districts",
            ),
            claim(  # the quote is not on the page: dropped by code, never checked
                MISSING_STATEMENT, "the screening budget was doubled in the last financial year"
            ),
            claim(  # a nearby town: kept; its period quote lacks 2023, so the period is cleared
                NEARBY_STATEMENT,
                "Kestrel Point, 27.0% of adults with hypertension had it controlled",
                kind=ClaimKind.STATISTIC, labels=labels(control, "2023", "Kestrel Point"),
                statistic=statistic("27.0%"), label_quotes=period_quote,
            ),
            claim(  # a town beyond geography.nearby_km: dropped, never checked
                ELSEWHERE_STATEMENT,
                "Port Ostra, 19.0% of adults with hypertension had it controlled",
                kind=ClaimKind.STATISTIC, labels=labels(control, None, "Port Ostra"),
                statistic=statistic("19.0%"),
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
        label=VerdictLabel.SUPPORTED, rationale="The passages state the figure and its period.",
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
    await sync_gazetteer(relational, PLACE + TOWN + NEAR_TOWN)
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
