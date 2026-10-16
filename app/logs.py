"""Structured logs (E-09, BD-58). One set-up for the app: every line carries the trace ID
of the run or question it belongs to, as text locally or as one JSON object per line.
Fetched text is never logged (CLAUDE.md); local trace files are the only place for it."""

import json
import logging
from datetime import UTC, datetime

from app.ports.tracing import TRACE_ID


class _TraceId(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.trace_id = TRACE_ID.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        body = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "trace_id": getattr(record, "trace_id", "-"),
            "msg": record.getMessage(),
        }
        if record.exc_info:
            body["exc"] = self.formatException(record.exc_info)
        return json.dumps(body, ensure_ascii=False)


TEXT = "%(asctime)s %(levelname)-7s %(name)s [%(trace_id)s] %(message)s"


def setup_logging(level: str, fmt: str) -> None:
    """Configure the root logger once (`logging.level`, `logging.format` [tunable]);
    Uvicorn's own loggers keep their handlers."""
    handler = logging.StreamHandler()
    handler.addFilter(_TraceId())
    handler.setFormatter(JsonFormatter() if fmt == "json" else logging.Formatter(TEXT))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
