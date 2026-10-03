"""Cities and runs over HTTP (LLD-4 §3.2): session required, place resolution, and the
error codes for run start. The run itself is covered offline in
tests/acceptance/test_thin_slice.py."""

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.workflow.runner import (
    DailyRunLimitError,
    PlaceNotFoundError,
    RunInProgressError,
    StartedRun,
)
from tests.unit.fake_adapters import probes as fake_probes
from tests.unit.fake_adapters import relational as fake_relational
from tests.unit.test_api import REGISTRY


def place(gid: str, name: str, score: float, population: int) -> dict[str, object]:
    return {
        "gazetteer_id": gid, "name": name, "admin1_name": "West Coast",
        "country_name": "Norvania", "country_iso2": "XN", "population": population,
        "score": score,
    }  # fmt: skip


class FakeManager:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.started: list[str] = []

    async def start(self, gazetteer_id: str) -> StartedRun:
        if self.error is not None:
            raise self.error
        self.started.append(gazetteer_id)
        return StartedRun(run_id="run_test1", city_id="city_test1")


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, valid_env: dict[str, str]) -> Iterator[TestClient]:
    for name, value in valid_env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(fake_probes, "DOWN", set())
    with TestClient(
        create_app(env_file=None, registry=REGISTRY), base_url="https://testserver"
    ) as c:
        yield c


@pytest.fixture
def signed_in(client: TestClient, valid_env: dict[str, str]) -> TestClient:
    client.post("/api/v1/session", json={"access_code": valid_env["ACCESS_CODE"]})
    return client


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("post", "/api/v1/cities/resolve"),
        ("post", "/api/v1/runs"),
        ("get", "/api/v1/runs/run_x"),
        ("get", "/api/v1/runs/run_x/events"),
    ],
)
def test_city_and_run_endpoints_need_a_session(client: TestClient, method: str, path: str) -> None:
    response = client.request(method, path, json={"query": "Halden Bay", "gazetteer_id": "1"})
    assert response.status_code == 401


def test_resolve_marks_a_clear_match_exact(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    places = [place("9000001", "Halden Bay", 1.0, 420000), place("9000003", "Halden", 0.6, 38000)]
    monkeypatch.setattr(fake_relational, "PLACES", places)  # fmt: skip
    body = signed_in.post("/api/v1/cities/resolve", json={"query": "halden bay"}).json()
    assert body["exact"] is True
    assert [c["gazetteer_id"] for c in body["candidates"]] == ["9000001", "9000003"]
    assert "score" not in body["candidates"][0]


def test_resolve_is_not_exact_when_another_candidate_is_close(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    places = [
        place("9000001", "Halden Bay", 1.0, 420000),
        place("9000004", "Halden Bay", 0.95, 900),
    ]
    monkeypatch.setattr(fake_relational, "PLACES", places)  # fmt: skip
    body = signed_in.post("/api/v1/cities/resolve", json={"query": "Halden Bay"}).json()
    assert body["exact"] is False


def test_start_run_returns_202_with_the_events_url(signed_in: TestClient) -> None:
    manager = FakeManager()
    signed_in.app.state.runs = manager  # type: ignore[attr-defined]
    response = signed_in.post("/api/v1/runs", json={"gazetteer_id": "9000001"})
    assert response.status_code == 202
    assert response.json() == {
        "run_id": "run_test1", "city_id": "city_test1", "status": "queued",
        "events_url": "/api/v1/runs/run_test1/events",
    }  # fmt: skip
    assert manager.started == ["9000001"]


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (RunInProgressError("run_other"), 409, "run_in_progress"),
        (DailyRunLimitError(), 429, "daily_run_limit"),
        (PlaceNotFoundError("1"), 404, "place_not_found"),
    ],
)
def test_start_run_errors_use_the_documented_codes(
    signed_in: TestClient, error: Exception, status: int, code: str
) -> None:
    signed_in.app.state.runs = FakeManager(error)  # type: ignore[attr-defined]
    response = signed_in.post("/api/v1/runs", json={"gazetteer_id": "9000001"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


def test_get_run_returns_status_summary_and_versions(
    signed_in: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 10, 3, 9, 0, tzinfo=UTC)
    monkeypatch.setattr(fake_relational, "RUNS", {"run_test1": {
        "run_id": "run_test1", "city_id": "city_test1", "status": "completed",
        "started_at": now, "finished_at": now, "summary": {"claims": {"supported": 1}},
        "versions": {"checker": "gpt-6-luna / checker@v1+abcd1234"}, "budget": {}, "error": None,
    }})  # fmt: skip
    body = signed_in.get("/api/v1/runs/run_test1").json()
    assert body["status"] == "completed"
    assert body["summary"] == {"claims": {"supported": 1}}
    assert signed_in.get("/api/v1/runs/run_missing").status_code == 404
