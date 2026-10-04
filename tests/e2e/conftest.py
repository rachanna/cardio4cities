"""The web smoke test's site (D3-4, BD-41): the built web app and the real API, served by
Uvicorn in a background thread over the Halden Bay retrieval fixture (Postgres, the Neo4j
graph, an in-memory claim index) with scripted models. Stores are opened inside the
server's own event loop, which is why the app's lifespan is replaced here."""

import os
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI

from app.adapters.postgres.relational import PostgresRelational
from app.adapters.renderer.fpdf2 import Fpdf2Renderer
from app.api.auth import AccessConfig
from app.api.limits import FailureLimiter
from app.container import Container
from app.main import WEB_DIRS, create_app
from app.prompts.reporter.schema import AnalysisOutput, DimensionIntro
from app.settings import load_settings
from scripts import eval_rag
from scripts.reference.yaml_reference import read_indicators, read_slots
from tests.contract.conftest import database_url, migrated  # noqa: F401
from tests.support.gazetteer import NEAR_TOWN, PLACE, TOWN, sync_gazetteer
from tests.support.thin_slice import reachable_graph
from tests.support.workflow_fakes import HashEmbeddings, MemoryVector

ACCESS_CODE = "halden-bay-viewer"
ADMIN_CODE = "halden-bay-presenter"
SIGNING = "e2e-session-signing-only-0001"  # signs test sessions only
WEB_OUT = Path(__file__).resolve().parents[2] / "web" / "out"


@dataclass
class Site:
    url: str
    city_id: str


class FixtureModels:
    """Classifies a question as the fixture says, answers faithfully, writes no prose."""

    def __init__(self) -> None:
        self.cases = {c["question"]: c for c in eval_rag.load_yaml("questions.yaml")}

    async def complete(
        self, role: str, system: str, user: str, schema: type[Any], params: Any
    ) -> Any:
        from app.ports.llm import LLMResult

        if role == "classifier":
            question = user.split("<question>")[-1].split("</question>")[0]
            case = self.cases.get(question, {"classified": {"question_type": "open"}})
            parsed: Any = eval_rag.classified(case)
            self._asked = list(parsed.slot_ids)
        elif role == "answerer":
            parsed = eval_rag.faithful(getattr(self, "_asked", []))(user)
        elif schema is DimensionIntro:
            parsed = DimensionIntro(sentences=[])
        else:
            parsed = AnalysisOutput(points=[])
        return LLMResult(
            parsed=parsed, raw_text=parsed.model_dump_json(), model_id="scripted",
            family="scripted", tokens_in=1, tokens_out=1, cost_micro_usd=0,
        )  # fmt: skip


def _app(database: str, env: Mapping[str, str]) -> FastAPI:
    app = create_app(env_file=None)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        settings = load_settings({**env, "DATABASE_URL": database})
        store = PostgresRelational(database)
        await store.reference.sync_indicators(read_indicators())
        await store.reference.sync_slots(read_slots())
        await sync_gazetteer(store, PLACE + TOWN + NEAR_TOWN)
        graph = await reachable_graph()
        await graph.delete_group(eval_rag.CITY_ID)
        embeddings, vector = HashEmbeddings(), MemoryVector()
        collection = f"claim_index__{embeddings.key}"
        await eval_rag.load_fixture(store, graph, vector, embeddings, collection)
        app.state.container = Container(
            settings=settings, relational=store, graph=graph, vector=vector, embeddings=embeddings,
            llm={"anthropic": FixtureModels()}, renderer=Fpdf2Renderer(),
        )  # fmt: skip
        app.state.access = AccessConfig(ACCESS_CODE, ADMIN_CODE, SIGNING)
        app.state.session_limiter = FailureLimiter()
        try:
            yield
        finally:
            await graph.delete_group(eval_rag.CITY_ID)
            await graph.close()
            await store.close()

    app.router.lifespan_context = lifespan
    return app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def site(migrated: str, valid_env: dict[str, str]) -> Iterator[Site]:  # noqa: F811
    if not (WEB_OUT / "index.html").exists():
        message = "the web app is not built: run `uv run poe web`"
        if os.environ.get("C4C_REQUIRE_WEB") == "1":
            pytest.fail(message)
        pytest.skip(message)
    assert WEB_DIRS[0] == WEB_OUT  # the API serves this build at /
    port = _free_port()
    config = uvicorn.Config(
        _app(migrated, valid_env), host="127.0.0.1", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 60
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            pytest.fail("the test server did not start")
        time.sleep(0.1)
    try:
        yield Site(f"http://127.0.0.1:{port}", eval_rag.CITY_ID)
    finally:
        server.should_exit = True
        thread.join(timeout=30)
