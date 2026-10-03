"""Pinned-IP fetcher (LLD-2 §9.3, AT-23; httpx chosen over httpx2 in BD-07).

The connection is dialled to the address the crawl gate checked, never to a fresh DNS
answer, so DNS rebinding cannot redirect a request to a private address. The hostname
is still used for the Host header, TLS SNI and certificate verification. One request,
no redirects: the collector re-gates every hop.
"""

import asyncio
import socket
import ssl
from collections.abc import Callable, Iterable
from typing import Any

import httpcore
import httpx

from app.ports.errors import FetchError
from app.ports.fetch import FetchLimits, FetchResult
from app.settings import Settings

Dial = Callable[[str, int], tuple[str, int]]
Resolver = Callable[[str], "asyncio.Future[list[str]] | Any"]


class _PinnedBackend(httpcore.AsyncNetworkBackend):
    """Ignores the host httpcore asks for and dials the pinned address."""

    def __init__(self, pinned_ip: str, dial: Dial | None) -> None:
        self._ip, self._dial = pinned_ip, dial
        self._inner = httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[Any] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        target, target_port = self._dial(self._ip, port) if self._dial else (self._ip, port)
        return await self._inner.connect_tcp(
            target, target_port, timeout, local_address, socket_options
        )

    async def connect_unix_socket(
        self, path: str, timeout: float | None = None, socket_options: Iterable[Any] | None = None
    ) -> httpcore.AsyncNetworkStream:
        raise FetchError("unix sockets are never used")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


class _PinnedTransport(httpx.AsyncBaseTransport):
    def __init__(self, pinned_ip: str, ssl_context: ssl.SSLContext, dial: Dial | None) -> None:
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=ssl_context,
            network_backend=_PinnedBackend(pinned_ip, dial),
            max_connections=1,
            retries=0,
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        core_request = httpcore.Request(
            method=request.method,
            url=httpcore.URL(
                scheme=request.url.raw_scheme,
                host=request.url.raw_host,
                port=request.url.port,
                target=request.url.raw_path,
            ),
            headers=request.headers.raw,
            content=request.stream,
            extensions=request.extensions,
        )
        core_response = await self._pool.handle_async_request(core_request)
        return httpx.Response(
            status_code=core_response.status,
            headers=core_response.headers,
            stream=_Stream(core_response),
            extensions=core_response.extensions,
        )

    async def aclose(self) -> None:
        await self._pool.aclose()


class _Stream(httpx.AsyncByteStream):
    def __init__(self, response: httpcore.Response) -> None:
        self._response = response

    async def __aiter__(self):  # type: ignore[no-untyped-def]
        async for part in self._response.aiter_stream():
            yield part

    async def aclose(self) -> None:
        await self._response.aclose()


async def _getaddrinfo(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return []
    return sorted({str(info[4][0]) for info in infos})


class PinnedFetcher:
    """FetchPort. `resolver` and `dial` exist for tests: a fake DNS and a route from
    fictional public addresses to a local test server. Production uses neither."""

    def __init__(
        self,
        resolver: Callable[[str], Any] | None = None,
        dial: Dial | None = None,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        self._resolver = resolver or _getaddrinfo
        self._dial = dial
        self._ssl = ssl_context or ssl.create_default_context()

    async def resolve(self, host: str) -> list[str]:
        return list(await self._resolver(host))

    async def fetch(self, url: str, pinned_ip: str, limits: FetchLimits) -> FetchResult:
        timeout = httpx.Timeout(
            limits.read_timeout_s, connect=limits.connect_timeout_s, pool=limits.connect_timeout_s
        )
        headers = {
            "user-agent": limits.user_agent,
            "accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9,*/*;q=0.1",
        }
        transport = _PinnedTransport(pinned_ip, self._ssl, self._dial)
        try:
            async with (
                httpx.AsyncClient(
                    transport=transport, timeout=timeout, follow_redirects=False, headers=headers
                ) as client,
                client.stream("GET", url) as response,
            ):
                body = bytearray()
                truncated = False
                async for part in response.aiter_raw():
                    body += part
                    if len(body) > limits.max_bytes:
                        truncated = True
                        break
                content = b"" if truncated else _decode(bytes(body), response.headers)
                return FetchResult(
                    url=url,
                    status=response.status_code,
                    headers={k.lower(): v for k, v in response.headers.items()},
                    content=content,
                    content_type=response.headers.get("content-type"),
                    truncated=truncated,
                )
        # The custom transport bypasses httpx's own error mapping, so httpcore errors are
        # caught here too; every network failure surfaces as FetchError, never a crash.
        except (httpx.TimeoutException, httpcore.TimeoutException) as exc:
            raise FetchError(f"timeout: {type(exc).__name__}", timeout=True) from exc
        except (
            httpx.HTTPError,
            httpcore.NetworkError,
            httpcore.ProtocolError,
            httpcore.UnsupportedProtocol,
            OSError,
            ssl.SSLError,
        ) as exc:
            raise FetchError(f"network error: {type(exc).__name__}") from exc


def _decode(raw: bytes, headers: httpx.Headers) -> bytes:
    """Undo Content-Encoding (gzip, deflate, br) after the size check on the raw bytes."""
    encoding = headers.get("content-encoding", "").lower()
    if not encoding or encoding == "identity" or not raw:
        return raw
    try:
        response = httpx.Response(200, headers={"content-encoding": encoding}, content=raw)
        return response.content
    except httpx.DecodingError as exc:
        raise FetchError("could not decode the response body") from exc


def make(settings: Settings) -> PinnedFetcher:
    return PinnedFetcher()
