"""Cities and runs (LLD-4 §3.2) and the event stream (LLD-4 §4, R-80, AT-30)."""

import asyncio
import json
import re
import time
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from app.api.auth import Session, current_session
from app.api.errors import ApiError, dependency_unavailable
from app.api.schemas import (
    PlaceCandidate,
    ResolveRequest,
    ResolveResponse,
    RunResponse,
    StartRunRequest,
    StartRunResponse,
)
from app.domain.vocab import EventType
from app.ports.repos import RelationalPort
from app.workflow.graph_marker import GraphNotReadyError
from app.workflow.runner import (
    DailyRunLimitError,
    PlaceNotFoundError,
    RunInProgressError,
    RunManager,
)

router = APIRouter(tags=["runs"])
SessionDep = Annotated[Session, Depends(current_session)]
EXACT_MARGIN = 0.1  # LLD-4 §3.2: no other candidate within this similarity
RETRY_MS = 2000  # LLD-4 §4: retry hint sent once
TERMINAL = frozenset({"completed", "stopped_by_budget", "failed"})
LAST_EVENT_ID = re.compile(r"\d{1,18}")  # an event sequence number that fits a bigint


def _relational(request: Request) -> RelationalPort:
    relational: RelationalPort | None = request.app.state.container.relational
    if relational is None:
        raise dependency_unavailable("postgres", "The research store is not available.")
    return relational


@router.post("/cities/resolve", response_model=ResolveResponse)
async def resolve(body: ResolveRequest, request: Request, _: SessionDep) -> ResolveResponse:
    rows = await _relational(request).reference.search_places(body.query)
    query = body.query.strip().casefold()
    exact = (
        bool(rows)
        and rows[0]["name"].casefold() == query
        and (len(rows) == 1 or float(rows[0]["score"]) - float(rows[1]["score"]) > EXACT_MARGIN)
    )
    return ResolveResponse(
        exact=exact,
        candidates=[PlaceCandidate.model_validate(r) for r in rows],
    )


@router.post("/runs", status_code=202, response_model=StartRunResponse)
async def start_run(body: StartRunRequest, request: Request, _: SessionDep) -> StartRunResponse:
    manager: RunManager = request.app.state.runs
    try:
        started = await manager.start(body.gazetteer_id)
    except GraphNotReadyError as exc:  # BD-25: the run is refused, the app keeps serving
        raise dependency_unavailable(
            "neo4j", f"The knowledge graph cannot take a new run yet: {exc}"
        ) from exc
    except RunInProgressError as exc:
        raise ApiError(
            409,
            "run_in_progress",
            "Another city is being researched. Wait for it to finish.",
            {"run_id": exc.run_id},
        ) from exc
    except DailyRunLimitError as exc:
        raise ApiError(
            429, "daily_run_limit", "Today's research limit is reached. Try again tomorrow."
        ) from exc
    except PlaceNotFoundError as exc:
        raise ApiError(404, "place_not_found", "That place is not in the gazetteer.") from exc
    except Exception as exc:
        if not await _reachable(_relational(request)):  # a store outage is a 503, not a 500
            raise dependency_unavailable(
                "postgres", "The research store is not available. Try again in a minute."
            ) from exc
        raise
    return StartRunResponse(
        run_id=started.run_id,
        city_id=started.city_id,
        status="queued",
        events_url=f"/api/v1/runs/{started.run_id}/events",
    )


async def _reachable(relational: RelationalPort) -> bool:
    try:
        await relational.ping()
    except Exception:
        return False
    return True


async def _run_row(request: Request, run_id: str) -> dict[str, Any]:
    row = await _relational(request).runs.run_row(run_id)
    if row is None:
        raise ApiError(404, "not_found", "That run does not exist.")
    return row


@router.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str, request: Request, _: SessionDep) -> RunResponse:
    return RunResponse.model_validate(await _run_row(request, run_id))


def _frame(event: dict[str, Any]) -> str:
    data = json.dumps(event["payload"], default=str, separators=(",", ":"))
    return f"id: {event['seq']}\nevent: {event['type']}\ndata: {data}\n\n"


async def event_frames(
    relational: RelationalPort,
    run_id: str,
    after_seq: int,
    poll_s: float,
    heartbeat_s: float,
    disconnected: Any = None,
) -> AsyncIterator[str]:
    """Replay stored events after `after_seq` in order, then follow new ones. Every frame
    comes from Postgres, so a reconnect sees no duplicates and no gaps (AT-30)."""
    yield f"retry: {RETRY_MS}\n\n"
    last_seq, last_sent = after_seq, time.monotonic()
    while True:
        rows = await relational.runs.events_after(run_id, last_seq)
        for row in rows:
            yield _frame(row)
            last_seq, last_sent = row["seq"], time.monotonic()
            if row["type"] == EventType.RUN_FINISHED.value:
                return
        if rows:
            continue
        run = await relational.runs.run_row(run_id)
        if run is None or run["status"] in TERMINAL:
            # run_finished is stored before the status, but it may have landed after the
            # read above: read once more, so the stream always ends with it (RV-036)
            for row in await relational.runs.events_after(run_id, last_seq):
                yield _frame(row)
            return
        if disconnected is not None and await disconnected():
            return
        if time.monotonic() - last_sent >= heartbeat_s:
            yield ": heartbeat\n\n"
            last_sent = time.monotonic()
        await asyncio.sleep(poll_s)


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    request: Request,
    _: SessionDep,
    last_event_id: Annotated[str | None, Header()] = None,
) -> StreamingResponse:
    if last_event_id and not LAST_EVENT_ID.fullmatch(last_event_id):
        # Not silently 0: that replays everything as duplicates (code review RV-036, RV-070)
        raise ApiError(
            400, "invalid_last_event_id", "Last-Event-ID must be the number of an event."
        )
    after = int(last_event_id) if last_event_id else 0
    await _run_row(request, run_id)
    stream = request.app.state.container.settings.config.stream
    frames = event_frames(
        _relational(request),
        run_id,
        after,
        stream.poll_interval_s,
        stream.heartbeat_s,
        request.is_disconnected,
    )
    return StreamingResponse(
        frames,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
