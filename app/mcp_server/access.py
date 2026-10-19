"""Who may call the tools-and-prompts server, and how much (E-15, BD-60).

Every HTTP request needs a bearer token from `mcp.clients`; a missing or unknown token is
refused with 401, a caller over its `calls_per_minute` with 429. Searches are counted
against the caller's `searches_per_day` by the search tool. Outside MCP clients do not
spend from a research run's budget ledger, so these limits are their budget. Each request
leaves one audit line: caller, MCP method and name, status, time. Arguments and results
are never logged."""

import hmac
import json
import logging
import time
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from starlette.types import ASGIApp, Message, Receive, Scope, Send

log = logging.getLogger("app.mcp_server.audit")


@dataclass(frozen=True)
class Caller:
    name: str
    calls_per_minute: int
    searches_per_day: int


@dataclass
class _Usage:
    calls: deque[float] = field(default_factory=deque)
    day: date | None = None
    searches: int = 0


class Access:
    def __init__(self, tokens: Mapping[str, Caller]) -> None:
        self._tokens = [(t.encode(), c) for t, c in tokens.items() if t]
        self._usage: dict[str, _Usage] = {}

    def identify(self, authorization: str | None) -> Caller | None:
        """The caller a `Bearer <token>` header names; constant-time comparison."""
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        given = authorization[7:].strip().encode()
        found = None
        for token, caller in self._tokens:
            if hmac.compare_digest(given, token):
                found = caller
        return found

    def _of(self, caller: Caller) -> _Usage:
        return self._usage.setdefault(caller.name, _Usage())

    def allow_call(self, caller: Caller, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        calls = self._of(caller).calls
        while calls and calls[0] <= now - 60:
            calls.popleft()
        if len(calls) >= caller.calls_per_minute:
            return False
        calls.append(now)
        return True

    def allow_search(self, caller: Caller, today: date | None = None) -> bool:
        today = datetime.now(UTC).date() if today is None else today
        usage = self._of(caller)
        if usage.day != today:
            usage.day, usage.searches = today, 0
        if usage.searches >= caller.searches_per_day:
            return False
        usage.searches += 1
        return True


def _header(scope: Scope, name: bytes) -> str | None:
    for key, value in scope.get("headers", []):
        if key.lower() == name:
            return str(value.decode("latin-1"))
    return None


class AccessGate:
    """ASGI middleware in front of the MCP endpoint."""

    def __init__(self, app: ASGIApp, access: Access) -> None:
        self._app = app
        self._access = access

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)  # lifespan: the server's own start-up
            return
        caller = self._access.identify(_header(scope, b"authorization"))
        if caller is None:
            await _refuse(send, 401, "a valid bearer token is required")
            self._audit(None, scope, 401, 0.0)
            return
        if not self._access.allow_call(caller):
            await _refuse(send, 429, "too many calls; try again in a minute")
            self._audit(caller, scope, 429, 0.0)
            return
        started, status = time.perf_counter(), 500

        async def tracked(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
            await send(message)

        try:
            await self._app(scope, receive, tracked)
        finally:
            self._audit(caller, scope, status, (time.perf_counter() - started) * 1000)

    @staticmethod
    def _audit(caller: Caller | None, scope: Scope, status: int, ms: float) -> None:
        log.info(
            "mcp %s %s by %s: %d in %.0f ms",
            _header(scope, b"mcp-method") or scope.get("method", "-"),
            _header(scope, b"mcp-name") or "-",
            caller.name if caller else "unknown",
            status,
            ms,
        )


async def _refuse(send: Send, status: int, detail: str) -> None:
    body = json.dumps({"error": detail}).encode()
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if status == 401:
        headers.append((b"www-authenticate", b'Bearer realm="cardio4cities-tools"'))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})
