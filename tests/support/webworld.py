"""A small fictional web for collection tests: one local HTTP server answering for several
`*.halden-bay.test` sites by Host header, a fake DNS, and a dial map that routes the fake
public addresses to the server. The real gate, pinning and fetch code runs unchanged.

Every request is logged with its arrival time, so tests can prove that no content
request was made (AT-04) and that requests were spaced (AT-05).
"""

import http.server
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from app.adapters.fetch.httpx_pinned import PinnedFetcher
from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser
from app.workflow.collection import CollectionParams, Collector, FetchKind

UA = "CARDIO4CitiesResearchBot/0.1 (+https://github.com/rachanna/cardio4cities)"


@dataclass
class Reply:
    status: int = 200
    body: bytes = b""
    content_type: str | None = "text/html; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)


Route = Reply | Callable[[], Reply]


@dataclass
class Hit:
    host: str
    path: str
    at: float


class WebWorld:
    def __init__(self) -> None:
        self.sites: dict[str, dict[str, Route]] = {}
        self.dns: dict[str, list[str]] = {}
        self.log: list[Hit] = []
        self._lock = threading.Lock()
        self._server: http.server.ThreadingHTTPServer | None = None
        self.port = 0

    # --- building the world -------------------------------------------------------

    def site(self, host: str, ip: str, routes: dict[str, Route]) -> None:
        self.sites[host] = routes
        self.dns[host] = [ip]

    def paths(self, host: str) -> list[str]:
        return [h.path for h in self.log if h.host == host]

    # --- plumbing -------------------------------------------------------------------

    async def resolve(self, host: str) -> list[str]:
        return list(self.dns.get(host, []))

    def dial(self, ip: str, port: int) -> tuple[str, int]:
        """Every fake public address is served by the local server."""
        if any(ip in ips for ips in self.dns.values()):
            return "127.0.0.1", self.port
        return ip, port  # anything else is dialled for real (and should never happen)

    def _handler(self) -> type[http.server.BaseHTTPRequestHandler]:
        world = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                host = (self.headers.get("Host") or "").split(":")[0]
                with world._lock:
                    world.log.append(Hit(host, self.path, time.monotonic()))
                route = world.sites.get(host, {}).get(self.path)
                reply = route() if callable(route) else route
                if reply is None:
                    reply = Reply(404, b"not found", "text/plain")
                self.send_response(reply.status)
                if reply.content_type:
                    self.send_header("content-type", reply.content_type)
                for name, value in reply.headers.items():
                    self.send_header(name, value)
                self.send_header("content-length", str(len(reply.body)))
                self.end_headers()
                self.wfile.write(reply.body)

            def log_message(self, *args: object) -> None:
                pass

        return Handler

    @contextmanager
    def running(self) -> Iterator["WebWorld"]:
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.port = self._server.server_address[1]
        thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        thread.start()
        try:
            yield self
        finally:
            self._server.shutdown()
            self._server.server_close()

    def fetcher(self) -> PinnedFetcher:
        return PinnedFetcher(resolver=self.resolve, dial=self.dial)


class CountingBudget:
    """Stands in for the BudgetLedger (D2-5): counts reservations."""

    def __init__(self) -> None:
        self.reserved: list[FetchKind] = []

    async def reserve(self, kind: FetchKind) -> None:
        self.reserved.append(kind)


def params(**overrides: object) -> CollectionParams:
    values: dict[str, object] = {
        "user_agent": UA,
        "allowed_ports": (80, 443),
        "min_interval_s": 0.0,
        "concurrency": 6,
        "max_bytes": 1_000_000,
        "connect_timeout_s": 3.0,
        "read_timeout_s": 3.0,
        "robots_timeout_s": 3.0,
    }
    values.update(overrides)
    return CollectionParams(**values)  # type: ignore[arg-type]


def collector(
    world: WebWorld, budget: CountingBudget | None = None, **overrides: object
) -> Collector:
    return Collector(
        world.fetcher(),
        ProtegoRobotsParser(),
        DocumentParser(),
        budget or CountingBudget(),
        params(**overrides),
    )


def article(sentence: str = "", words: int = 60) -> bytes:
    """A readable HTML page about the fictional city, well over 200 characters of text."""
    filler = " ".join(["The Norvania Health Directorate reported on heart health."] * (words // 8))
    return (
        "<html><head><title>Heart health in Halden Bay</title></head><body><main><article>"
        f"<h1>Heart health in Halden Bay</h1><p>{sentence}</p><p>{filler}</p>"
        "</article></main></body></html>"
    ).encode()


ALLOW_ALL = Reply(200, b"User-agent: *\nAllow: /\n", "text/plain")
