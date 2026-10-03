"""Workflow checkpoints (LLD-2 §17, DEC-02): the LangGraph checkpointer that lets a run
stopped by a restart resume where it was. LangGraph is the workflow framework, not a
vendor SDK; the store behind it is an adapter (`app/adapters/postgres/checkpointer.py`)."""

from typing import Any, Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver


class CheckpointUnavailableError(RuntimeError):
    """The checkpointer cannot run in this process; runs go on without checkpoints."""


class CheckpointPort(Protocol):
    async def saver(self) -> BaseCheckpointSaver[Any]:
        """The ready checkpointer (set up on first use). Raises CheckpointUnavailableError."""
        ...

    async def close(self) -> None: ...
