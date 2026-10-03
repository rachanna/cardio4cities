"""The event stream replays from Postgres (AT-30, R-80): no duplicates, no gaps, and a
close after run_finished, on an offline research run of slot S04."""

import pytest

from app.adapters.postgres.relational import PostgresRelational
from app.api.routers.runs import event_frames
from tests.support.thin_slice import (
    Slice,
)

pytestmark = pytest.mark.db


async def _frames(store: PostgresRelational, run_id: str, after: int) -> list[str]:
    return [f async for f in event_frames(store, run_id, after, poll_s=0.01, heartbeat_s=60)]


def _ids(frames: list[str]) -> list[int]:
    return [int(f.split("\n")[0][4:]) for f in frames if f.startswith("id: ")]


async def test_event_stream_replays_without_duplicates_or_gaps(thin_slice: Slice) -> None:
    """AT-30: a full replay, then a reconnect with Last-Event-ID mid-run."""
    s = thin_slice
    full = await _frames(s.store, s.run_id, 0)
    assert full[0] == "retry: 2000\n\n"
    ids = _ids(full)
    assert ids == list(range(1, len(ids) + 1))
    assert "event: run_finished" in full[-1]
    assert "event: run_started" in full[1]

    middle = ids[len(ids) // 2]
    resumed = _ids(await _frames(s.store, s.run_id, middle))
    assert resumed == ids[middle:]
    assert _ids(await _frames(s.store, s.run_id, ids[-1])) == []  # nothing after the end
