"""FastAPI application factory (ID-01): the API under /api/v1, the web app at /.

Settings are loaded and validated, the container built and reference data
checked in the lifespan: a bad configuration or an unloaded database stops
start-up with a message naming each problem (R-82), while importing this
module stays free of side effects. Start-up also refuses a graph whose embeddings were
made by another model, and resumes a run a stopped process left behind (D2-5, BD-14).
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import errors
from app.api.auth import AccessConfig
from app.api.limits import FailureLimiter
from app.api.routers import health, runs, session
from app.api.routers.health import HealthService
from app.container import ADAPTERS, AdapterRegistry, Container, build_container
from app.ports.graph import GraphPort
from app.settings import (
    ConfigError,
    Settings,
    check_embedding_dimension,
    check_indicator_codes,
    check_reference_slots,
    load_settings,
)
from app.workflow.deps import chunk_collection, claim_collection
from app.workflow.graph_marker import GraphNotReadyError, ensure_graph_marker
from app.workflow.runner import RunManager

log = logging.getLogger(__name__)
APP_VERSION = "0.1.0"
ROOT = Path(__file__).resolve().parents[1]
# The Next.js export (D3-4) once built; until then the placeholder page.
WEB_DIRS = (ROOT / "web" / "out", ROOT / "web" / "placeholder")


async def check_reference_data(container: Container) -> None:
    """LLD-4 §5.2 reference-data checks against the database (BD-02)."""
    if container.relational is None:
        return
    reference = container.relational.reference
    try:
        slot_ids = await reference.slot_ids()
        codes = await reference.indicator_codes()
    except Exception as exc:
        raise ConfigError(
            [
                f"reference data could not be read ({type(exc).__name__}); "
                f"run `poe migrate` and `poe reference` against DATABASE_URL"
            ]
        ) from exc
    problems = [*check_reference_slots(slot_ids), *check_indicator_codes(codes)]
    if problems:
        raise ConfigError(problems)


async def check_graph_marker(graph: GraphPort | None, embedding_key: str) -> str | None:
    """R-82 at start-up: warn only. A graph that is unreachable, unmarked or from another
    model refuses runs with a 503 (`ensure_graph_marker` before every run, BD-25); it
    never stops the app from starting. Returns the problem, if any."""
    if graph is None:
        return None
    try:
        await ensure_graph_marker(graph, embedding_key)
    except GraphNotReadyError as exc:
        log.warning("runs will be refused until the graph is ready: %s", exc)
        return str(exc)
    return None


# Ports a run cannot do without: a missing adapter refuses start-up (code review RV-037)
REQUIRED_PORTS = frozenset({
    "relational", "checkpointer", "llm", "embeddings", "search", "fetch", "robots",
    "parser", "vector", "snapshots", "graph",
})  # fmt: skip


def check_adapters(missing: list[str], registry: AdapterRegistry) -> None:
    """A role on a provider with no adapter used to start with a warning and fail every
    check at run time with KeyError; now start-up refuses and names it (BD-25). A port the
    registry does not offer at all (a partial build for API tests) is not refused."""
    required = [
        m for m in missing
        if (port := m.partition(":")[0]) in REQUIRED_PORTS and registry.get(port)
    ]  # fmt: skip
    if required:
        raise ConfigError(
            [f"no adapter for {m.replace(':', ' provider ')}; choose a supported provider"
             for m in required]
        )  # fmt: skip


async def check_vector_store(container: Container, settings: Settings) -> None:
    """R-82, BD-02(5): the embedding model's dimension is the configured one, and no
    existing collection holds vectors of another size. An unreachable store is left to
    the health check (code review RV-034)."""
    embeddings, vector = container.embeddings, container.vector
    if embeddings is None or vector is None:
        return
    cfg = settings.config.embeddings
    problems: list[str] = []
    for name in (chunk_collection(cfg.key), claim_collection(cfg.key)):
        try:
            existing = await vector.collection_dimension(name)
        except Exception as exc:
            log.warning("vector collections not checked (%s)", type(exc).__name__)
            return
        problems += check_embedding_dimension(cfg.dimension, embeddings.dimension, name, existing)
    if problems:
        raise ConfigError(sorted(set(problems)))


async def _checkpoints(manager: RunManager) -> bool | None:
    try:
        return await manager.checkpoints_available()
    except Exception as exc:
        log.warning("checkpoints not checked (%s)", type(exc).__name__)
        return None


def _lifespan(
    env_file: Path | None, registry: AdapterRegistry | None
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if env_file is not None:
            load_dotenv(env_file, override=False)  # never overrides real environment variables
        settings = load_settings()
        container = build_container(settings, registry)
        manager: RunManager | None = None
        try:
            check_adapters(container.missing, ADAPTERS if registry is None else registry)
            await check_reference_data(container)
            await check_vector_store(container, settings)
            await check_graph_marker(container.graph, settings.config.embeddings.key)
            if container.missing:
                log.warning("adapters not built yet: %s", ", ".join(container.missing))
            access = settings.config.access
            app.state.container = container
            app.state.access = AccessConfig(
                access_code=settings.secret(access.access_code_env),
                admin_code=settings.secret(access.admin_code_env),
                session_secret=settings.secret(access.session_secret_env),
            )
            app.state.session_limiter = FailureLimiter()
            manager = app.state.runs = RunManager(container, settings)
            checkpoints: bool | None = None
            if container.relational is not None:
                # Never raises: a store outage must not stop the app or spend a resume
                resumed = await manager.resume_stranded()
                if resumed:
                    log.warning("resumed runs left by a stopped process: %s", ", ".join(resumed))
                manager.start_watching()  # heartbeat and take over quiet runs (BD-25)
                checkpoints = await _checkpoints(manager)
            app.state.health = HealthService(
                relational=container.relational,
                probes=container.probes,
                same_family_checker=settings.same_family_checker,
                app_version=APP_VERSION,
                checkpoints=checkpoints,
            )
            yield
        finally:
            if manager is not None:  # runs stop, keeping their checkpoints, before stores close
                await manager.shutdown()
            await container.close()

    return lifespan


def create_app(
    env_file: Path | None = Path(".env"), registry: AdapterRegistry | None = None
) -> FastAPI:
    app = FastAPI(
        title="CARDIO4Cities", version=APP_VERSION, lifespan=_lifespan(env_file, registry)
    )
    errors.install(app)
    app.include_router(session.router, prefix="/api/v1")
    app.include_router(health.router, prefix="/api/v1")
    app.include_router(runs.router, prefix="/api/v1")
    web_dir = next((d for d in WEB_DIRS if d.is_dir()), None)
    if web_dir is not None:  # mounted last: API routes take precedence
        app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
    return app


app = create_app()
