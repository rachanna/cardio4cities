"""Offline multi-slot runs for D2-5 (BD-14): coverage, re-planning, the budget stop, the
shared fetch cache, resume and programme status. Real graph, gate, fetcher, parser and
Postgres; scripted models; a small fictional web about Halden Bay, Norvania.

The sparse web has three sites: one readable page with nothing to extract, one site
whose robots.txt refuses every path, and one page about a heart programme (slot S07)."""

import re
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.graph.graphiti import GraphitiGraph
from app.adapters.parse.documents import DocumentParser
from app.adapters.postgres.relational import PostgresRelational
from app.adapters.snapshots.postgres import PostgresSnapshots
from app.domain.vocab import EntityType, ProgrammeStatus, RelationType, VerdictLabel
from app.ports.checkpoint import CheckpointPort
from app.prompts.checker.schema import CheckerOutput
from app.prompts.extractor.schema import ExtractorOutput, RelationOut
from app.prompts.planner.schema import PlannedQuery, PlannerOutput, SlotQueries
from app.settings import Settings, load_settings
from app.workflow.runner import RunManager
from scripts.reference.yaml_reference import read_indicators, read_slots
from tests.support.gazetteer import NEAR_TOWN, PLACE, TOWN, sync_gazetteer
from tests.support.thin_slice import claim
from tests.support.webworld import ALLOW_ALL, Reply, WebWorld, article
from tests.support.workflow_fakes import (
    HashEmbeddings,
    ListSearch,
    MemoryVector,
    Ports,
    ScriptedLLM,
)

EMPTY_HOST = "library.halden-bay.test"
EMPTY_URL = f"http://{EMPTY_HOST}/annual-notes"
CLOSED_HOST = "archive.halden-bay.test"
CLOSED_URL = f"http://{CLOSED_HOST}/records"
PROGRAMME_HOST = "heart.halden-bay.test"
PROGRAMME_URL = f"http://{PROGRAMME_HOST}/programme"
DENY_ALL = Reply(200, b"User-agent: *\nDisallow: /\n", "text/plain")

PROGRAMME = "Halden Bay Heart Health Programme"
PLANNED_SENTENCE = (
    "In January 2023 the Halden Bay Health Office announced the Halden Bay Heart Health "
    "Programme, planned to start the following year."
)
RUNNING_SENTENCE = (
    "Since March 2025 the Halden Bay Health Office has run the Halden Bay Heart Health "
    "Programme in every district clinic."
)
PLANNED_QUOTE = "the Halden Bay Health Office announced the Halden Bay Heart Health Programme"
RUNNING_QUOTE = (
    "Since March 2025 the Halden Bay Health Office has run the Halden Bay Heart Health "
    "Programme in every district clinic"
)


def queries_for(slot_id: str, round_no: int) -> list[tuple[str, str]]:
    """The scripted planner's queries: new ones every round, one in the primary language."""
    return [
        (f"Halden Bay {slot_id} evidence round {round_no}", "en"),
        (f"Halden Bay {slot_id} kilder runde {round_no}", "nv"),
    ]


def planner(user: str) -> PlannerOutput:
    round_no = int(re.search(r"^round: (\d+)$", user, re.M).group(1))  # type: ignore[union-attr]
    slots = re.findall(r"^- (S\d\d): ", user, re.M)
    return PlannerOutput(
        slots=[
            SlotQueries(
                slot_id=s,
                queries=[
                    PlannedQuery(text=t, lang=lang, purpose="test")
                    for t, lang in queries_for(s, round_no)
                ],
            )
            for s in slots
        ]
    )


def search_for(routes: dict[str, str], rounds: int = 3) -> ListSearch:
    """Every query of a slot finds the slot's one URL."""
    by_query = {
        text: [url]
        for slot_id, url in routes.items()
        for round_no in range(rounds)
        for text, _ in queries_for(slot_id, round_no)
    }
    return ListSearch([], by_query=by_query)


def runs(subject: str, valid_from: str, status: ProgrammeStatus) -> RelationOut:
    return RelationOut(
        subject_name=subject,
        subject_type=EntityType.ORGANIZATION,
        relation_type=RelationType.RUNS,
        object_name=PROGRAMME,
        object_type=EntityType.PROGRAMME,
        valid_from=valid_from,
        valid_to=None,
        programme_status=status,
    )


def extractor(user: str) -> ExtractorOutput:
    """Nothing on the sparse pages; two dated programme claims on the programme page."""
    if PLANNED_SENTENCE not in user:
        return ExtractorOutput(claims=[])
    office = "Halden Bay Health Office"
    return ExtractorOutput(
        claims=[
            claim(
                f"The {office} announced the {PROGRAMME} as planned in January 2023.",
                PLANNED_QUOTE,
                slot_id="S07",
                kind="relation",
                relation=runs(office, "2023-01", ProgrammeStatus.PLANNED),
            ),
            claim(
                f"The {office} has run the {PROGRAMME} since March 2025.",
                RUNNING_QUOTE,
                slot_id="S07",
                kind="relation",
                relation=runs(office, "2025-03", ProgrammeStatus.RUNNING),
            ),
        ]
    )


def checker(_: str) -> CheckerOutput:
    return CheckerOutput(
        label=VerdictLabel.SUPPORTED,
        rationale="The passage states it.",
        scope_verified=True,
        period_verified=True,
        issues=[],
    )


def programme_page() -> bytes:
    return article(f"{PLANNED_SENTENCE} {RUNNING_SENTENCE}")


def sparse_world() -> WebWorld:
    world = WebWorld()
    world.site(
        EMPTY_HOST,
        "93.184.216.40",
        {"/robots.txt": ALLOW_ALL, "/annual-notes": Reply(200, article())},
    )
    world.site(
        CLOSED_HOST, "93.184.216.41", {"/robots.txt": DENY_ALL, "/records": Reply(200, article())}
    )
    world.site(
        PROGRAMME_HOST,
        "93.184.216.42",
        {"/robots.txt": ALLOW_ALL, "/programme": Reply(200, programme_page())},
    )
    return world


async def load_reference(relational: PostgresRelational) -> None:
    await relational.reference.sync_indicators(read_indicators())
    await relational.reference.sync_slots(read_slots())
    await sync_gazetteer(relational, PLACE + TOWN + NEAR_TOWN)


def settings_for(
    database_url: str, env: dict[str, str], config_dir: Path | None = None
) -> Settings:
    full = {**env, "DATABASE_URL": database_url}
    return load_settings(full, config_dir) if config_dir else load_settings(full)


@dataclass
class Scripts:
    anthropic: ScriptedLLM
    openai: ScriptedLLM


def scripts(
    planner_: Callable[[str], Any] = planner,
    extractor_: Callable[[str], Any] = extractor,
    checker_: Callable[[str], Any] = checker,
) -> Scripts:
    return Scripts(
        ScriptedLLM("anthropic", {"planner": planner_, "extractor": extractor_}),
        ScriptedLLM("openai", {"checker": checker_}),
    )


@asynccontextmanager
async def ports_for(
    relational: PostgresRelational,
    settings: Settings,
    world: WebWorld,
    search: ListSearch,
    models: Scripts,
    graph: GraphitiGraph,
    vector: MemoryVector,
    checkpointer: CheckpointPort | None = None,
) -> AsyncIterator[Ports]:
    snapshots = PostgresSnapshots(
        settings.secret(settings.config.relational.dsn_env), settings.config.snapshots.max_bytes
    )
    try:
        with world.running():
            yield Ports(
                relational=relational,
                llm={"anthropic": models.anthropic, "openai": models.openai},
                search=search,
                fetch=world.fetcher(),
                robots=ProtegoRobotsParser(),
                parser=DocumentParser(),
                embeddings=HashEmbeddings(),
                vector=vector,
                snapshots=snapshots,
                graph=graph,
                checkpointer=checkpointer,
            )
    finally:
        await snapshots.close()


async def run_to_end(manager: RunManager, slots: list[str]) -> str:
    started = await manager.start("9000001", slots=slots)
    await manager.wait(started.run_id)
    return started.run_id
