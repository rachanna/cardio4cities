"""EventEmitter (LLD-2 §10): every event is numbered and written to Postgres first; the
stream endpoint replays and follows from Postgres, so a reconnecting client sees every
event exactly once (AT-30). Nothing is streamed that is not stored."""

from typing import Any

from app.domain.vocab import EventType
from app.ports.repos import RunRepo
from app.workflow.ids import new_id


class EventEmitter:
    def __init__(self, runs: RunRepo) -> None:
        self._runs = runs

    async def emit(self, run_id: str, type_: EventType, payload: dict[str, Any]) -> int:
        return await self._runs.append_event(run_id, new_id("evt"), type_.value, payload)
