"""Starting and running research runs (LLD-2 §2, LLD-4 §3.2). One run at a time per
deployment (CON-10). The graph runs as a background task in the API process; everything
it does reaches the browser through the event log, so the stream replays from Postgres.

The runner receives the ports from the composition root as a `RunPorts`; it never
imports adapters."""

import asyncio
import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

import yaml

from app.domain.models import CityIdentity
from app.domain.params import (
    BadgeParams,
    ConsistencyParams,
    EntityParams,
    GeographyParams,
    QuoteParams,
    VerifyParams,
)
from app.domain.vocab import EventType
from app.ports.embeddings import EmbeddingsPort
from app.ports.fetch import FetchPort
from app.ports.graph import GraphPort
from app.ports.llm import LLMPort
from app.ports.parse import ParserPort
from app.ports.repos import RelationalPort
from app.ports.robots import RobotsParser
from app.ports.search import SearchPort
from app.ports.snapshots import SnapshotPort
from app.ports.vector import VectorPort
from app.prompts.loader import load_prompt
from app.settings import ModelRef, RoleConfig, Settings
from app.workflow.budget import BudgetLedger, BudgetLimits
from app.workflow.collection import CollectionParams, Collector
from app.workflow.deps import Binding, RoleBinding, RunDeps, WindowParams
from app.workflow.entities import EntityResolver
from app.workflow.events import EventEmitter
from app.workflow.graph import build_graph
from app.workflow.ids import new_id
from app.workflow.rules.chunking import ChunkParams
from app.workflow.rules.selection import PublisherTable, publisher_table
from app.workflow.rules.thresholds import ThresholdRule, threshold_table
from app.workflow.state import RunState

log = logging.getLogger(__name__)
REFERENCE_DIR = Path(__file__).resolve().parents[2] / "reference"
VERSIONED_ROLES = ("planner", "extractor", "checker")


class RunPorts(Protocol):
    """What a run needs from the composition root (the `Container` satisfies it)."""

    relational: RelationalPort | None
    llm: dict[str, LLMPort]
    search: SearchPort | None
    fetch: FetchPort | None
    robots: RobotsParser | None
    parser: ParserPort | None
    embeddings: EmbeddingsPort | None
    vector: VectorPort | None
    snapshots: SnapshotPort | None
    graph: GraphPort | None


class RunInProgressError(Exception):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} is in progress")
        self.run_id = run_id


class DailyRunLimitError(Exception):
    pass


class PlaceNotFoundError(Exception):
    pass


@dataclass(frozen=True)
class StartedRun:
    run_id: str
    city_id: str


def _binding(ref: ModelRef | RoleConfig, family: str | None = None) -> Binding:
    return Binding(
        provider=ref.provider,
        model=ref.model,
        family=ref.family or family or ref.provider,
        effort=ref.effort,
        temperature=ref.temperature,
    )


def _need[T](port: T | None, name: str) -> T:
    if port is None:
        raise RuntimeError(f"the workflow needs a {name} port; none is configured")
    return port


def role_bindings(settings: Settings) -> dict[str, RoleBinding]:
    roles = {}
    for name, role in settings.config.llm.roles.items():
        roles[name] = RoleBinding(
            primary=_binding(role),
            escalate_to=_binding(role.escalate_to, role.family) if role.escalate_to else None,
            fallback=_binding(role.fallback) if role.fallback else None,
        )
    return roles


def model_versions(roles: dict[str, RoleBinding]) -> dict[str, str]:
    """`run.versions`: the model and prompt version of each role the run uses (R-74)."""
    return {
        role: f"{roles[role].primary.model} / {load_prompt(role).prompt_version}"
        for role in VERSIONED_ROLES
    }


@dataclass
class RunManager:
    ports: RunPorts
    settings: Settings
    reference_dir: Path = REFERENCE_DIR
    tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _publishers: PublisherTable | None = None
    _thresholds: tuple[ThresholdRule, ...] = ()

    def _reference(self, name: str) -> Any:
        return yaml.safe_load((self.reference_dir / name).read_text(encoding="utf-8"))

    @property
    def relational(self) -> RelationalPort:
        if self.ports.relational is None:
            raise RuntimeError("no relational store configured")
        return self.ports.relational

    async def start(self, gazetteer_id: str, slots: Sequence[str] | None = None) -> StartedRun:
        """Create the city (first time) and the run, then run the graph in the background.
        `slots` narrows the run for spikes and tests; the API always runs every slot."""
        runs = self.relational.runs
        async with self._lock:
            if (active := await runs.active_run()) is not None:
                raise RunInProgressError(active)
            if await runs.runs_today() >= self.settings.config.limits.runs_per_day:
                raise DailyRunLimitError()
            place = await self.relational.reference.place_identity(gazetteer_id)
            if place is None:
                raise PlaceNotFoundError(gazetteer_id)
            city_id = await runs.city_for_place(gazetteer_id)
            if city_id is None:
                city_id = new_id("city")
                await runs.create_city(CityIdentity(city_id=city_id, admin2_name=None, **place))
            city = await runs.city_identity(city_id)
            run_id = new_id("run")
            deps = await self.build_deps(run_id)
            await runs.create_run(
                run_id, city_id, deps.ledger.limits.__dict__, model_versions(deps.roles)
            )
        slot_ids = list(slots) if slots is not None else sorted(deps.slots)
        task = asyncio.create_task(self._run(deps, city, slot_ids), name=run_id)
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))
        return StartedRun(run_id=run_id, city_id=city_id)

    async def wait(self, run_id: str) -> None:
        if (task := self.tasks.get(run_id)) is not None:
            await asyncio.shield(task)

    async def _run(self, deps: RunDeps, city: CityIdentity, slot_ids: list[str]) -> None:
        state: RunState = {
            "run_id": deps.run_id,
            "city": city,
            "round": 0,
            "slots_to_work": slot_ids,
        }
        try:
            await build_graph().ainvoke(
                state,
                {
                    "configurable": {"deps": deps},
                    "max_concurrency": self.settings.config.llm.concurrency,
                },
            )
        except Exception as exc:  # the run fails visibly, never silently
            log.exception("run %s failed", deps.run_id)
            await deps.events.emit(
                deps.run_id,
                EventType.RUN_FINISHED,
                {"status": "failed", "error": type(exc).__name__},
            )
            await self.relational.runs.set_status(deps.run_id, "failed", type(exc).__name__)

    async def build_deps(self, run_id: str) -> RunDeps:
        p, cfg = self.ports, self.settings.config
        search, fetch, robots = (
            _need(p.search, "search"),
            _need(p.fetch, "fetch"),
            _need(p.robots, "robots"),
        )
        parser, embeddings = _need(p.parser, "parser"), _need(p.embeddings, "embeddings")
        vector, snapshots = _need(p.vector, "vector"), _need(p.snapshots, "snapshots")
        graph = _need(p.graph, "graph")
        if self._publishers is None:
            self._publishers = publisher_table(self._reference("publishers.yaml"))
            self._thresholds = threshold_table(self._reference("thresholds.yaml"))
        b = cfg.budget
        ledger = BudgetLedger(
            BudgetLimits(
                wall_clock_s=b.wall_clock_s,
                searches=b.searches,
                fetches=b.fetches,
                tokens=b.tokens or 0,
                cost_micro_usd=b.cost_micro_usd or 0,
                wind_down_at=b.wind_down_at,
            )
        )
        f = cfg.fetch
        collector = Collector(
            fetch,
            robots,
            parser,
            ledger,
            CollectionParams(
                user_agent=cfg.app.user_agent,
                allowed_ports=tuple(f.allowed_ports),
                min_interval_s=f.min_interval_s,
                concurrency=f.concurrency,
                max_bytes=f.max_bytes,
                connect_timeout_s=f.connect_timeout_s,
                read_timeout_s=f.read_timeout_s,
                robots_timeout_s=f.robots_timeout_s,
            ),
        )
        reference = self.relational.reference
        deps = RunDeps(
            run_id=run_id,
            relational=self.relational,
            llm=p.llm,
            roles=role_bindings(self.settings),
            search=search,
            search_provider=cfg.search.provider,
            collector=collector,
            embeddings=embeddings,
            vector=vector,
            graph=graph,
            entities=EntityResolver(
                self.relational.entities,
                embeddings,
                ledger,
                EntityParams(**cfg.entity.model_dump()),
            ),
            snapshots=snapshots,
            ledger=ledger,
            events=EventEmitter(self.relational.runs),
            slots={s.slot_id: s for s in await reference.slots()},
            indicators={i.code: i for i in await reference.indicators()},
            publishers=self._publishers,
            thresholds=self._thresholds,
            quote=QuoteParams(**cfg.quote.model_dump()),
            verify=VerifyParams(**cfg.verify.model_dump()),
            consistency=ConsistencyParams(
                agree_pp=Decimal(str(cfg.consistency.agree_pp)),
                agree_rel=Decimal(str(cfg.consistency.agree_rel)),
            ),
            badge=BadgeParams(**cfg.badge.model_dump()),
            geography=GeographyParams(nearby_km=cfg.geography.nearby_km),
            chunk=ChunkParams(**cfg.chunk.model_dump()),
            window=WindowParams(**cfg.extract.model_dump()),
            max_new_urls=cfg.select.max_new_urls_per_slot_round,
            today=date.today,
        )
        await vector.ensure_collection(deps.collection, embeddings.dimension)
        await vector.ensure_collection(deps.claim_collection, embeddings.dimension)
        return deps
