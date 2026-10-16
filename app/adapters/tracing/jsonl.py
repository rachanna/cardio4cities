"""Local trace files (E-09, BD-58): `traces/<trace id>/trace.jsonl`, one JSON record per
span or event, for debugging on this machine only.

Owner decision (BD-58): these files may hold fetched text and full prompts, which logs
never do; the directory is git-ignored, and the tracer is refused under `APP_ENV=deployed`
(settings check). Secrets never: any attribute whose name looks like a key, token,
password, secret or connection string is redacted. Long text keeps its first
`tracing.max_text_chars` characters and its total length."""

import json
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.ports.tracing import TRACE_ID
from app.settings import Settings

# Names that hold secrets; "token" only at the end, so usage counts (`tokens_in`) stay
_SECRET = re.compile(
    r"(api[_-]?key|private[_-]?key|token$|password|passwd|secret|credential|dsn|authorization|cookie)",
    re.I,
)
_SAFE_ID = re.compile(r"[^A-Za-z0-9_.-]")
_SPANS: ContextVar[tuple[int, ...]] = ContextVar("c4c_trace_spans", default=())


def clean(value: Any, limit: int, key: str = "") -> Any:
    """JSON-safe, secrets redacted, long strings bounded."""
    if key and _SECRET.search(key):
        return "[redacted]"
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return {"text": value[:limit], "chars": len(value), "truncated": True}
    if isinstance(value, dict):
        return {str(k): clean(v, limit, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [clean(v, limit) for v in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    dump = getattr(value, "model_dump", None)
    if callable(dump):
        return clean(dump(mode="json"), limit)
    return str(value)


class JsonlTracer:
    def __init__(self, root: Path, max_text_chars: int) -> None:
        self._root = root
        self._limit = max_text_chars
        self._next = 0

    def _path(self) -> Path:
        trace_id = TRACE_ID.get() or "untraced"
        folder = self._root / _SAFE_ID.sub("_", trace_id)
        folder.mkdir(parents=True, exist_ok=True)
        return folder / "trace.jsonl"

    def _write(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, ensure_ascii=False, default=str)
        with self._path().open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    @asynccontextmanager
    async def span(self, name: str, **attrs: Any) -> AsyncIterator[None]:
        self._next += 1
        span_id, stack = self._next, _SPANS.get()
        token = _SPANS.set((*stack, span_id))
        started, status = time.perf_counter(), "ok"
        try:
            yield
        except BaseException as exc:
            status = type(exc).__name__
            raise
        finally:
            _SPANS.reset(token)
            self._write(
                {
                    "ts": datetime.now(UTC).isoformat(),
                    "kind": "span",
                    "name": name,
                    "span": span_id,
                    "parent": stack[-1] if stack else None,
                    "ms": round((time.perf_counter() - started) * 1000, 1),
                    "status": status,
                    "attrs": clean(attrs, self._limit),
                }
            )

    def event(self, name: str, **attrs: Any) -> None:
        stack = _SPANS.get()
        self._write(
            {
                "ts": datetime.now(UTC).isoformat(),
                "kind": "event",
                "name": name,
                "span": stack[-1] if stack else None,
                "attrs": clean(attrs, self._limit),
            }
        )


def make(settings: Settings) -> JsonlTracer:
    t = settings.config.tracing
    return JsonlTracer(Path(t.jsonl_dir), t.max_text_chars)
