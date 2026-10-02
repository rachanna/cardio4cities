"""FastAPI application factory (ID-01). Routers are mounted as their tasks land.

Settings are loaded and validated, and the container built, in the lifespan:
a bad configuration stops start-up with a message naming each problem (R-82),
while importing this module stays free of side effects.
"""

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI

from app.container import build_container
from app.settings import load_settings

log = logging.getLogger(__name__)


def _lifespan(env_file: Path | None) -> Callable[[FastAPI], AbstractAsyncContextManager[None]]:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if env_file is not None:
            load_dotenv(env_file, override=False)  # never overrides real environment variables
        settings = load_settings()
        container = build_container(settings)
        if container.missing:
            log.warning("adapters not built yet: %s", ", ".join(container.missing))
        app.state.container = container
        yield

    return lifespan


def create_app(env_file: Path | None = Path(".env")) -> FastAPI:
    return FastAPI(title="CARDIO4Cities", version="0.1.0", lifespan=_lifespan(env_file))


app = create_app()
