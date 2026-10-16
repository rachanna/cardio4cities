"""What a trace record may hold (E-09, BD-58; E-14, BD-59): every tracer cleans its
attributes here, so the trace files and LangSmith redact and bound text the same way."""

import re
from typing import Any

# Names that hold secrets; "token" only at the end, so usage counts (`tokens_in`) stay
_SECRET = re.compile(
    r"(api[_-]?key|private[_-]?key|token$|password|passwd|secret|credential|dsn|authorization|cookie)",
    re.I,
)


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
