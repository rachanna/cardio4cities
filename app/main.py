"""FastAPI application factory (ID-01): the API under /api/v1, the web app at /.

Settings are loaded and validated, the container built and reference data
checked in the lifespan: a bad configuration or an unloaded database stops
start-up with a message naming each problem (R-82), while importing this
module stays free of side effects.
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
from app.container import AdapterRegistry, Container, build_container
from app.settings import ConfigError, check_indicator_codes, check_reference_slots, load_settings
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


def _lifespan(
    env_file: Path | None, registry: AdapterRegistry | None
) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if env_file is not None:
            load_dotenv(env_file, override=False)  # never overrides real environment variables
        settings = load_settings()
        container = build_container(settings, registry)
        try:
            await check_reference_data(container)
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
            app.state.runs = RunManager(container, settings)
            app.state.health = HealthService(
                relational=container.relational,
                probes=container.probes,
                same_family_checker=settings.same_family_checker,
                app_version=APP_VERSION,
            )
            yield
        finally:
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
