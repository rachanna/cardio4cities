"""Tracing (HLD §13.4, R-71; E-09, BD-58). A span times one step and records what it did;
an event records one fact inside the current span. Tracing never changes behaviour: with
no tracer configured, `NoTracing` does nothing at all.

`TRACE_ID` names the trace a task belongs to: a run's ID, or a question's trace ID. It is a
context variable, so every task a run or a question starts inherits it."""

from collections.abc import AsyncIterator, Sequence
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from contextvars import ContextVar
from typing import Any, Protocol

TRACE_ID: ContextVar[str | None] = ContextVar("c4c_trace_id", default=None)


class TracingPort(Protocol):
    def span(self, name: str, **attrs: Any) -> AbstractAsyncContextManager[None]: ...

    def event(self, name: str, **attrs: Any) -> None: ...


class NoTracing:
    """The default: nothing is recorded and nothing changes."""

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[None]:
        yield

    def event(self, name: str, **attrs: Any) -> None:
        return None


class Tracers:
    """Every configured tracer at once; a tracer that fails never fails the step."""

    def __init__(self, tracers: Sequence[TracingPort]) -> None:
        self._tracers = list(tracers)

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[None]:
        """Opening or closing a tracer's span may fail; the step's own outcome, value or
        exception, is what the caller sees either way."""
        opened: list[AbstractAsyncContextManager[None]] = []
        for tracer in self._tracers:
            try:
                cm = tracer.span(name, **attrs)
                await cm.__aenter__()
                opened.append(cm)
            except Exception:  # noqa: S112 - tracing must never stop the work it traces
                continue
        error: BaseException | None = None
        try:
            yield
        except BaseException as exc:
            error = exc
            raise
        finally:
            for cm in reversed(opened):
                try:
                    if error is None:
                        await cm.__aexit__(None, None, None)
                    else:
                        await cm.__aexit__(type(error), error, error.__traceback__)
                except Exception:  # noqa: S112 - the step's own outcome stands
                    continue

    def event(self, name: str, **attrs: Any) -> None:
        for tracer in self._tracers:
            try:
                tracer.event(name, **attrs)
            except Exception:  # noqa: S112 - tracing must never stop the work it traces
                continue


def tracer_of(tracers: Sequence[TracingPort]) -> TracingPort:
    return Tracers(tracers) if tracers else NoTracing()
