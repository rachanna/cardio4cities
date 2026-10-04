"""Starting and running research runs (LLD-2 §2, LLD-4 §3.2). One run at a time per
deployment (CON-10). The graph runs as a background task in the API process; everything
it does reaches the browser through the event log, so the stream replays from Postgres.

The runner receives the ports from the composition root as a `RunPorts`; it never
imports adapters.

Checkpoints and resume (D2-5, BD-14): with a checkpointer, every step of a run is saved
under the run ID. At start-up, a run left `running` by a stopped process is resumed once
from its last checkpoint, with the budget counters it had used; a run that cannot be
resumed (no checkpoint, or already resumed once) is marked `failed`, visibly."""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from contextvars import ContextVar
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
    ReplanParams,
    VerifyParams,
)
from app.domain.vocab import EventType
from app.ports.checkpoint import CheckpointPort, CheckpointUnavailableError
from app.ports.embeddings import EmbeddingsPort
from app.ports.fetch import FetchPort
from app.ports.graph import GraphPort
from app.ports.llm import LLMPort
from app.ports.parse import ParserPort
from app.ports.repos import RelationalPort
from app.ports.robots import RobotsParser
from app.ports.search import SearchPort
from app.ports.snapshots import SnapshotPort
from app.ports.structured import StructuredDataPort
from app.ports.vector import VectorPort
from app.prompts.loader import load_prompt
from app.settings import ModelRef, RoleConfig, Settings
from app.workflow.budget import BudgetLedger, BudgetLimits
from app.workflow.collection import CollectionParams, Collector
from app.workflow.deps import Binding, RoleBinding, RunDeps, WindowParams
from app.workflow.entities import EntityResolver
from app.workflow.events import EventEmitter
from app.workflow.graph import build_graph
from app.workflow.graph_marker import ensure_graph_marker
from app.workflow.ids import new_id
from app.workflow.limits import LimitedEmbeddings, LimitedLLM
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
    structured: dict[str, StructuredDataPort]
    checkpointer: CheckpointPort | None


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


# The run a task belongs to: set in the run's task, inherited by every task it starts
RUN_ID: ContextVar[str | None] = ContextVar("c4c_run_id", default=None)


# Only the run's own work is cancelled: database pools also start tasks lazily inside a
# run's context, and cancelling those would break the pool for everything after
OWN_WORK = ("langgraph", "app.")


def _module(task: asyncio.Task[Any]) -> str:
    frame = getattr(task.get_coro(), "cr_frame", None)
    return str(frame.f_globals.get("__name__", "")) if frame is not None else ""


def _cancel_run_tasks(run_id: str) -> None:
    """Cancel every unfinished task running LangGraph or app code for `run_id`, except
    the caller."""
    me = asyncio.current_task()
    for task in asyncio.all_tasks():
        if (
            task is not me
            and not task.done()
            and task.get_context().get(RUN_ID) == run_id
            and _module(task).startswith(OWN_WORK)
        ):
            task.cancel()


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
    # This process, as the owner its runs record with their heartbeat (BD-25)
    owner: str = field(default_factory=lambda: f"proc_{uuid.uuid4().hex[:16]}")
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)
    _watcher: asyncio.Task[None] | None = field(default=None, repr=False)
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
            # The graph takes this run's embeddings only with this model's marker (BD-25)
            await ensure_graph_marker(self.ports.graph, self.settings.config.embeddings.key)
            run_id = new_id("run")
            deps = await self.build_deps(run_id)
            await runs.create_run(
                run_id,
                city_id,
                deps.ledger.limits.__dict__,
                model_versions(deps.roles),
                self.owner,
            )
        slot_ids = list(slots) if slots is not None else sorted(deps.slots)
        state: RunState = {
            "run_id": run_id,
            "city": city,
            "round": 0,
            "all_slots": slot_ids,
            "slots_to_work": slot_ids,
        }
        self._launch(deps, state)
        return StartedRun(run_id=run_id, city_id=city_id)

    async def wait(self, run_id: str) -> None:
        if (task := self.tasks.get(run_id)) is not None:
            await asyncio.shield(task)

    async def _saver(self) -> Any:
        """The checkpointer, or None when none is configured or it cannot run here."""
        if self.ports.checkpointer is None:
            return None
        try:
            return await self.ports.checkpointer.saver()
        except CheckpointUnavailableError as exc:
            log.warning("running without checkpoints: %s", exc)
            return None

    def _launch(self, deps: RunDeps, state: RunState | None) -> None:
        run_id = deps.run_id
        task = asyncio.create_task(self._run(deps, state), name=run_id)
        self.tasks[run_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(run_id, None))

    async def _run(self, deps: RunDeps, state: RunState | None) -> None:
        """`state` None: resume the run from its last checkpoint. A cancelled run (the
        process is stopping) stays `running`, so another process resumes it (BD-25)."""
        RUN_ID.set(deps.run_id)  # every task the run starts copies this context (BD-27)
        try:
            saver = await self._saver()
            deps.checkpointed = saver is not None  # shown in the run summary (BD-25)
            graph = build_graph(saver)
            await graph.ainvoke(
                state,
                {
                    "configurable": {"deps": deps, "thread_id": deps.run_id},
                    # Slots run side by side; what they share is limited per resource
                    # (model, embeddings, fetch, search), not by the number of slots.
                    "max_concurrency": max(len(deps.slots), 1),
                },
            )
        except asyncio.CancelledError:
            # LangGraph can leave sibling nodes running after a cancel (seen when the
            # cancel lands during a node's call): refuse their external calls and cancel
            # every task this run started, so a stopped run stops (BD-27)
            deps.ledger.stop()
            _cancel_run_tasks(deps.run_id)
            raise
        except Exception as exc:  # the run fails visibly, never silently
            log.exception("run %s failed", deps.run_id)
            await self._fail(deps.run_id, type(exc).__name__)

    async def _fail(self, run_id: str, error: str) -> None:
        await EventEmitter(self.relational.runs).emit(
            run_id, EventType.RUN_FINISHED, {"status": "failed", "error": error}
        )
        await self.relational.runs.set_status(run_id, "failed", error)

    async def resume_stranded(self, stale_after_s: float | None = None) -> list[str]:
        """Resume each run a stopped process left behind, once (BD-14). Only a run whose
        owner has gone quiet for `stale_after_s` (default `runs.stale_after_s`) is taken
        over, so a live run in another process is never run twice (BD-25). One run's
        failure never stops the others, and nothing here raises."""
        stale = self.settings.config.runs.stale_after_s if stale_after_s is None else stale_after_s
        resumed: list[str] = []
        try:
            rows = await self.relational.runs.stranded_runs()
            saver = await self._saver()
        except Exception as exc:  # the store is unreachable: try again on the next pass
            log.warning("stranded runs not checked (%s)", type(exc).__name__)
            return resumed
        for row in rows:
            run_id = row["run_id"]
            if run_id in self.tasks:
                continue  # this process is running it
            quiet = row.get("quiet_s")
            if quiet is not None and float(quiet) < stale and row.get("owner") != self.owner:
                continue  # another process is alive and owns it
            try:
                if await self._resume(row, saver, stale):
                    resumed.append(run_id)
            except Exception as exc:  # left for the next pass; the resume is not spent
                log.warning("run %s not resumed (%s)", run_id, type(exc).__name__)
        return resumed

    async def _resume(self, row: dict[str, Any], saver: Any, stale_after_s: float) -> bool:
        run_id = row["run_id"]
        checkpoint = (
            await saver.aget_tuple({"configurable": {"thread_id": run_id}})
            if saver is not None
            else None
        )
        if checkpoint is None or row["resume_attempts"] >= 1:
            reason = "no checkpoint" if checkpoint is None else "already resumed once"
            log.warning("run %s cannot be resumed (%s)", run_id, reason)
            await self._fail(run_id, f"interrupted by a restart ({reason})")
            return False
        # Everything that can fail on a store comes before the claim, so a failure here
        # does not spend the run's one resume (code review RV-035)
        deps = await self.build_deps(run_id)
        await ensure_graph_marker(self.ports.graph, self.settings.config.embeddings.key)
        if not await self.relational.runs.claim_stale(run_id, self.owner, stale_after_s):
            return False  # another process took it first
        deps.ledger.restore((row["budget"] or {}).get("used", {}))
        self._launch(deps, None)
        return True

    async def watch(self) -> None:
        """For the life of the process: keep this process's runs' heartbeat fresh and
        take over runs whose owner went quiet, such as an old instance during a deploy
        (BD-25). Never raises."""
        every = self.settings.config.runs.heartbeat_s
        while True:
            try:
                if self.tasks:
                    await self.relational.runs.heartbeat(self.owner)
                resumed = await self.resume_stranded()
                if resumed:
                    log.warning("took over stranded runs: %s", ", ".join(resumed))
            except Exception as exc:
                log.warning("run watch pass failed (%s)", type(exc).__name__)
            await asyncio.sleep(every)

    def start_watching(self) -> None:
        if self._watcher is None:
            self._watcher = asyncio.create_task(self.watch(), name="run-watch")

    async def shutdown(self) -> None:
        """Stop watching, then cancel this process's runs and wait for them before the
        adapters close. A cancelled run stays `running` with its checkpoint, so the next
        process resumes it (BD-25; code review RV-040)."""
        tasks = [t for t in (self._watcher, *self.tasks.values()) if t is not None]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.wait(tasks, timeout=self.settings.config.runs.shutdown_grace_s)

    async def checkpoints_available(self) -> bool:
        """False on Windows' Proactor loop, where runs cannot resume (BD-14)."""
        return await self._saver() is not None

    async def build_deps(self, run_id: str) -> RunDeps:
        p, cfg = self.ports, self.settings.config
        search, fetch, robots = (
            _need(p.search, "search"),
            _need(p.fetch, "fetch"),
            _need(p.robots, "robots"),
        )
        parser = _need(p.parser, "parser")
        embeddings = LimitedEmbeddings(
            _need(p.embeddings, "embeddings"), asyncio.Semaphore(cfg.embeddings.concurrency)
        )
        model_gate = asyncio.Semaphore(cfg.llm.concurrency)  # shared by every provider
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
                crawl_delay_cap_s=f.crawl_delay_cap_s,
                total_timeout_s=f.total_timeout_s,
            ),
        )
        reference = self.relational.reference
        events = EventEmitter(self.relational.runs)
        deps = RunDeps(
            run_id=run_id,
            relational=self.relational,
            llm={name: LimitedLLM(port, model_gate) for name, port in p.llm.items()},
            roles=role_bindings(self.settings),
            search=search,
            search_provider=cfg.search.provider,
            collector=collector,
            embeddings=embeddings,
            vector=vector,
            graph=graph,
            structured=dict(p.structured),
            entities=EntityResolver(
                self.relational.entities,
                embeddings,
                ledger,
                EntityParams(**cfg.entity.model_dump()),
            ),
            snapshots=snapshots,
            ledger=ledger,
            events=events,
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
            max_reused_urls=cfg.select.max_reused_per_slot_round,
            replan=ReplanParams(
                max_rounds=cfg.replan.max_rounds,
                max_rounds_wider_geo=cfg.replan.max_rounds_wider_geo,
                priority=tuple(cfg.replan.priority),
            ),
            queries_per_slot=cfg.plan.queries_per_slot,
            other_place_min_population=cfg.select.other_place_min_population,
            today=date.today,
        )

        async def warn(counter: str, used: float, limit: float) -> None:
            """`budget_warning` (LLD-2 §10.2), with the counters saved for a resume."""
            await events.emit(
                run_id,
                EventType.BUDGET_WARNING,
                {"counter": counter, "used": round(used, 1), "limit": round(limit, 1)},
            )
            await self.relational.runs.save_budget_used(run_id, ledger.snapshot())

        ledger.on_warning = warn
        await vector.ensure_collection(deps.collection, embeddings.dimension)
        await vector.ensure_collection(deps.claim_collection, embeddings.dimension)
        return deps
