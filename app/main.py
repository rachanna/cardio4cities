"""FastAPI application factory (ID-01). Routers are mounted as their tasks land.

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

from app.container import AdapterRegistry, Container, build_container
from app.settings import ConfigError, check_indicator_codes, check_reference_slots, load_settings

log = logging.getLogger(__name__)


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
            app.state.container = container
            yield
        finally:
            if container.relational is not None:
                await container.relational.close()

    return lifespan


def create_app(
    env_file: Path | None = Path(".env"), registry: AdapterRegistry | None = None
) -> FastAPI:
    return FastAPI(title="CARDIO4Cities", version="0.1.0", lifespan=_lifespan(env_file, registry))


app = create_app()
