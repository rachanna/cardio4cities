"""LangSmith tracing (E-14, BD-59): each span becomes a LangSmith run, nested as the spans
nest, so a research run, a question or a report is one trace. Local profiles only, on the
free Developer plan; the deployed profile refuses it (settings check).

Through the tracing port only: LangGraph's own tracing (`LANGSMITH_TRACING=true`) would
send the whole graph state unredacted and is refused at start-up. Attributes are cleaned
as in the trace files (`redact.clean`). A run is posted when its span opens, so a long
research run shows while it works, and patched with its outputs when the span closes; the
SDK sends both from a background thread, so tracing never waits on the network.

Root runs per UTC day are capped (`tracing.langsmith.max_traces_per_day` [tunable]) so the
free plan's monthly allowance holds; past the cap, spans are not recorded."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, date, datetime
from typing import Any

from langsmith import Client
from langsmith.run_trees import RunTree

from app.adapters.tracing.redact import clean
from app.ports.tracing import TRACE_ID
from app.settings import Settings

log = logging.getLogger(__name__)

_CURRENT: ContextVar[RunTree | None] = ContextVar("c4c_langsmith_run", default=None)
_UNRECORDED: ContextVar[bool] = ContextVar("c4c_langsmith_unrecorded", default=False)


def _text(value: Any) -> Any:
    """A bounded text as LangSmith shows text: its start and its length."""
    if isinstance(value, dict) and value.get("truncated"):
        return f"{value['text']}… [{value['chars']} characters, truncated]"
    return value


class LangsmithTracer:
    def __init__(
        self,
        client: Any,
        project: str,
        max_text_chars: int,
        max_traces_per_day: int,
        flush_timeout_s: float,
        tags: list[str],
    ) -> None:
        self._client = client
        self._project = project
        self._limit = max_text_chars
        self._max_roots = max_traces_per_day
        self._flush_timeout_s = flush_timeout_s
        self._tags = tags
        self._day: date | None = None
        self._roots = 0

    def _allow_root(self) -> bool:
        today = datetime.now(UTC).date()
        if today != self._day:
            self._day, self._roots = today, 0
        if self._roots >= self._max_roots:
            if self._roots == self._max_roots:
                log.warning("langsmith: %d traces today; not recording more", self._max_roots)
                self._roots += 1  # warn once a day
            return False
        self._roots += 1
        return True

    def _open(self, name: str, attrs: dict[str, Any], parent: RunTree | None) -> RunTree:
        llm = name.startswith("llm:")
        cleaned = clean(attrs, self._limit)
        metadata: dict[str, Any] = {}
        if llm:  # LangSmith shows a model call with its provider and model
            metadata = {
                "ls_provider": cleaned.get("provider"),
                "ls_model_name": cleaned.get("model"),
            }
        inputs: dict[str, Any] = {} if llm else {k: _text(v) for k, v in cleaned.items()}
        if parent is not None:
            return parent.create_child(
                name, "llm" if llm else "chain", inputs=inputs, extra={"metadata": metadata}
            )
        return RunTree(
            name=name,
            run_type="llm" if llm else "chain",
            inputs=inputs,
            project_name=self._project,
            ls_client=self._client,
            tags=list(self._tags),
            extra={"metadata": {**metadata, "trace_id": TRACE_ID.get()}},
        )

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[None]:
        parent = _CURRENT.get()
        if _UNRECORDED.get() or (parent is None and not self._allow_root()):
            skipped = _UNRECORDED.set(True)
            try:
                yield
            finally:
                _UNRECORDED.reset(skipped)
            return
        run = self._open(name, attrs, parent)
        run.post()
        token = _CURRENT.set(run)
        try:
            yield
        except BaseException as exc:
            run.end(error=_text(clean(f"{type(exc).__name__}: {exc}", self._limit)))
            raise
        else:
            run.end()
        finally:
            _CURRENT.reset(token)
            run.patch(exclude_inputs=False)
            if parent is not None and run in parent.child_runs:
                parent.child_runs.remove(run)  # sent; a long run holds no finished calls

    def event(self, name: str, **attrs: Any) -> None:
        run = _CURRENT.get()
        if run is None or _UNRECORDED.get():
            return
        a = clean(attrs, self._limit)
        if name == "llm.request":
            run.add_inputs(
                {
                    "messages": [
                        {"role": "system", "content": _text(a.get("system"))},
                        {"role": "user", "content": _text(a.get("user"))},
                    ]
                }
            )
            run.add_metadata({"params": a.get("params")})
        elif name == "llm.response":
            usage = a.get("usage") or {}
            tokens_in, tokens_out = int(usage.get("tokens_in", 0)), int(usage.get("tokens_out", 0))
            run.set(
                outputs={"output": _text(a.get("output"))},
                usage_metadata={
                    "input_tokens": tokens_in,
                    "output_tokens": tokens_out,
                    "total_tokens": tokens_in + tokens_out,
                },
            )
            run.add_metadata({"usage": usage})
        elif name == "llm.failed":
            run.add_metadata({"failure": {k: _text(v) for k, v in a.items()}})
        else:
            run.add_event({"name": name, "time": datetime.now(UTC).isoformat(), "kwargs": a})

    async def close(self) -> None:
        """Send what is queued before the app stops, waiting at most the configured time."""
        await asyncio.to_thread(self._client.flush, self._flush_timeout_s)


def _report_failure(exc: Exception) -> None:
    log.warning("langsmith: sending a trace failed (%s)", type(exc).__name__)


def make(settings: Settings) -> LangsmithTracer:
    t = settings.config.tracing
    if not t.langsmith_api_key_env or t.langsmith is None:
        raise ValueError("tracing.langsmith_api_key_env and tracing.langsmith are required")
    client = Client(
        api_url=settings.secret(t.langsmith.endpoint_env),
        api_key=settings.secret(t.langsmith_api_key_env),
        tracing_error_callback=_report_failure,
    )
    return LangsmithTracer(
        client,
        t.langsmith.project,
        t.max_text_chars,
        t.langsmith.max_traces_per_day,
        t.langsmith.flush_timeout_s,
        tags=[settings.env],
    )
