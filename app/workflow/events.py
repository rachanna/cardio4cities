"""EventEmitter (LLD-2 §10): every event is numbered and written to Postgres first; the
stream endpoint replays and follows from Postgres, so a reconnecting client sees every
event exactly once (AT-30). Nothing is streamed that is not stored."""

import json
from typing import Any

from app.domain.vocab import EventType
from app.ports.repos import RunRepo
from app.workflow.ids import stable_id


class EventEmitter:
    def __init__(self, runs: RunRepo) -> None:
        self._runs = runs

    async def emit(self, run_id: str, type_: EventType, payload: dict[str, Any]) -> int:
        """Stored before it is streamed. The ID comes from the event's content, so a step
        that a resume runs again returns the stored event instead of adding a duplicate."""
        body = json.dumps(payload, sort_keys=True, default=str)
        event_id = stable_id("evt", run_id, type_.value, body)
        return await self._runs.append_event(run_id, event_id, type_.value, payload)
