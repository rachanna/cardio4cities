"""Start-up and operations (BD-25; code review RV-014, RV-034, RV-035, RV-036, RV-037,
RV-039, RV-040, RV-069, RV-070, RV-071, RV-074, RV-108). Fakes only; fictional names."""

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.auth import AccessConfig, read_token
from app.api.routers.runs import event_frames
from app.main import check_adapters, check_vector_store, create_app
from app.settings import ConfigError, load_settings
from app.workflow.runner import RunManager
from tests.unit.fake_adapters import probes as fake_probes
from tests.unit.test_api import REGISTRY

# --- start-up checks --------------------------------------------------------------------


def test_a_role_on_a_provider_with_no_adapter_refuses_start_up() -> None:
    """RV-037: it used to start with a warning and fail every check with KeyError."""
    registry = {"llm": {"anthropic": "x:y", "openai": "x:y"}}
    with pytest.raises(ConfigError, match="no adapter for llm provider ollama"):
        check_adapters(["llm:ollama"], registry)


def test_a_port_the_registry_leaves_out_is_not_refused() -> None:
    """Partial registries build the API alone for tests; renderer and tracing come later."""
    check_adapters(["llm:anthropic", "renderer:weasyprint"], {"relational": {"postgres": "x:y"}})


class Vectors:
    def __init__(self, sizes: dict[str, int | None], fail: bool = False) -> None:
        self.sizes, self.fail = sizes, fail

    async def collection_dimension(self, name: str) -> int | None:
        if self.fail:
            raise ConnectionError("qdrant down")
        return self.sizes.get(name)


class Embeddings:
    def __init__(self, dimension: int) -> None:
        self.dimension = dimension


class Box:
    def __init__(self, embeddings: Any, vector: Any) -> None:
        self.embeddings, self.vector = embeddings, vector


async def test_a_collection_of_another_vector_size_refuses_start_up(
    valid_env: dict[str, str],
) -> None:
    """RV-034: changing the model but keeping the key would mix models silently."""
    settings = load_settings(valid_env)
    key = settings.config.embeddings.key
    dim = settings.config.embeddings.dimension
    with pytest.raises(ConfigError, match="would mix embedding models"):
        await check_vector_store(
            Box(Embeddings(dim), Vectors({f"source_chunks__{key}": dim + 1})),  # type: ignore[arg-type]
            settings,
        )
    with pytest.raises(ConfigError, match="the provider reports"):
        await check_vector_store(Box(Embeddings(dim + 2), Vectors({})), settings)  # type: ignore[arg-type]
    await check_vector_store(Box(Embeddings(dim), Vectors({})), settings)  # type: ignore[arg-type]
    await check_vector_store(Box(Embeddings(dim), Vectors({}, fail=True)), settings)  # type: ignore[arg-type]


# --- run manager -----------------------------------------------------------------------------


class BrokenRuns:
    async def stranded_runs(self) -> list[dict[str, Any]]:
        raise ConnectionError("postgres down")


class BrokenRelational:
    runs = BrokenRuns()


async def test_resuming_never_raises_when_the_store_is_down(valid_env: dict[str, str]) -> None:
    """RV-035: a store error used to escape the lifespan, so the app did not start."""
    ports = type("P", (), {"relational": BrokenRelational(), "checkpointer": None})()
    manager = RunManager(ports, load_settings(valid_env))
    assert await manager.resume_stranded() == []


async def test_shutdown_cancels_runs_before_the_stores_close(valid_env: dict[str, str]) -> None:
    """RV-040: a cancelled run stays `running` with its checkpoint, for the next process."""
    manager = RunManager(type("P", (), {})(), load_settings(valid_env))
    task = asyncio.create_task(asyncio.sleep(3600))
    manager.tasks["run_live"] = task
    await manager.shutdown()
    assert task.cancelled()


# --- API ------------------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> Iterator[TestClient]:
    for name, value in valid_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(fake_probes, "DOWN", set())
    with TestClient(
        create_app(env_file=None, registry=REGISTRY), base_url="https://testserver"
    ) as c:
        yield c


def test_liveness_needs_only_the_process_and_postgres(client: TestClient) -> None:
    """RV-039: the platform restarts a service whose check fails; a Neo4j restart must not."""
    fake_probes.DOWN.add("neo4j")
    assert client.get("/api/v1/health").status_code == 503
    live = client.get("/api/v1/live")
    assert (live.status_code, live.json()) == (200, {"status": "ok"})


def test_unknown_addresses_and_methods_use_the_error_envelope(client: TestClient) -> None:
    """RV-071."""
    missing = client.get("/api/v1/no-such-thing")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    assert client.get("/api").json()["error"]["code"] == "not_found"  # not the web app's page
    wrong = client.put("/api/v1/health")
    assert wrong.status_code == 405
    assert wrong.json()["error"]["code"] == "method_not_allowed"


@pytest.mark.parametrize("value", ["abc", "-1", "1e3", "9" * 19])
def test_a_last_event_id_that_is_not_an_event_number_is_refused(
    client: TestClient, valid_env: dict[str, str], value: str
) -> None:
    """RV-036, RV-070: it became 0 (a full replay as duplicates), or a database error."""
    client.post("/api/v1/session", json={"access_code": valid_env["ACCESS_CODE"]})
    response = client.get("/api/v1/runs/run_test1/events", headers={"Last-Event-ID": value})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_last_event_id"


def test_a_non_ascii_session_cookie_is_401_not_500() -> None:
    """RV-069: compare_digest raised TypeError."""
    assert read_token("payéload.sigé", "secret") is None


def test_access_secrets_never_appear_in_a_repr() -> None:
    """RV-074."""
    shown = repr(AccessConfig("ACCESS-123", "ADMIN-456", "SECRET-789"))
    assert not any(s in shown for s in ("ACCESS-123", "ADMIN-456", "SECRET-789"))


# --- the stream always ends with run_finished ---------------------------------------------


class RacingRuns:
    """`run_finished` lands between the empty read and the status read (RV-036)."""

    def __init__(self) -> None:
        self.reads = 0

    async def events_after(self, run_id: str, after: int, limit: int = 500) -> list[dict[str, Any]]:
        self.reads += 1
        if self.reads == 1:
            return []
        return [{"seq": 7, "type": "run_finished", "payload": {"status": "completed"}}]

    async def run_row(self, run_id: str) -> dict[str, Any]:
        return {"run_id": run_id, "status": "completed"}


async def test_the_stream_sends_run_finished_even_when_it_lands_late() -> None:
    relational = type("R", (), {"runs": RacingRuns()})()
    frames = [f async for f in event_frames(relational, "run_t", 6, 0.01, 15.0)]
    assert frames[-1].startswith("id: 7\nevent: run_finished")


# --- a stopped run stops (BD-28) -----------------------------------------------------------


async def test_a_stopped_ledger_refuses_every_call_without_counting_a_refusal() -> None:
    from app.workflow.budget import BudgetExhaustedError, BudgetLedger, BudgetLimits

    ledger = BudgetLedger(BudgetLimits(420, 64, 60, 0, 0, 0.85))
    ledger.stop()
    for kind in ("fetch", "model", "indexing"):
        with pytest.raises(BudgetExhaustedError):
            await ledger.reserve(kind)
    assert ledger.refused == set()  # not a budget stop: the run is not finishing here


async def test_cancelling_a_run_cancels_the_tasks_it_started(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LangGraph can leave a sibling node running when a cancel lands mid-call; every
    task the run started carries its run ID and is cancelled with it."""
    from app.workflow import runner as runner_module
    from app.workflow.runner import RUN_ID, _cancel_run_tasks

    monkeypatch.setattr(runner_module, "OWN_WORK", ("tests.unit.test_operations",))

    started: list[asyncio.Task[None]] = []

    async def run() -> None:
        RUN_ID.set("run_t")
        started.append(asyncio.create_task(_app_work()))  # inherits the run ID
        await _app_work()

    other = asyncio.create_task(_app_work())  # another run's or a request's task
    runner = asyncio.create_task(run())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    _cancel_run_tasks("run_t")
    await asyncio.sleep(0)
    assert started[0].cancelled()
    assert not other.cancelled()
    other.cancel()
    runner.cancel()


async def _app_work() -> None:
    """Stands in for a node's coroutine: the cancel only touches LangGraph and app code."""
    await asyncio.sleep(3600)
