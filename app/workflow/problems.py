"""Failures that cost one item, or one step, but never the slot (BD-21; LLD-2 §17).

A source that cannot be stored, a window the extractor could not read, a claim the
checker could not judge, a search that failed twice, or a whole node that raised: each is
stored as a `step_failed` event, so the stream, the run summary and a later review can
see what was lost. Only the error's type is stored for errors that can carry fetched
text; our own port errors carry our own message.
"""

import logging

from app.domain.vocab import EventType
from app.ports.errors import PortError
from app.workflow.deps import RunDeps
from app.workflow.state import SlotState

log = logging.getLogger(__name__)


def describe(exc: BaseException) -> str:
    """Never fetched text: vendor and library messages can quote the page."""
    if isinstance(exc, PortError):
        return f"{type(exc).__name__}: {exc}"
    return type(exc).__name__


async def step_failed(
    d: RunDeps, state: SlotState, stage: str, item: str | None, exc: BaseException
) -> None:
    error = describe(exc)
    log.warning("%s %s: %s failed for %s (%s)", state["run_id"], state["slot_id"], stage,
                item or "the whole step", error)  # fmt: skip
    await d.events.emit(
        state["run_id"],
        EventType.STEP_FAILED,
        {
            "slot_id": state["slot_id"],
            "round": state.get("round", 0),
            "stage": stage,
            "item": item,
            "error": error,
        },
    )
