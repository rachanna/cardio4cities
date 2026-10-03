"""HTTPS with a pinned IP (AT-23): the connection goes to the checked address while the
certificate is still verified against the hostname. Uses a throwaway CA (trustme)."""

import asyncio
import http.server
import ssl
import threading
from collections.abc import Iterator

import pytest
import trustme

from app.adapters.fetch.httpx_pinned import PinnedFetcher
from app.ports.errors import FetchError
from app.ports.fetch import FetchLimits

HOST, PUBLIC_IP = "secure.halden-bay.test", "93.184.216.34"
LIMITS = FetchLimits(max_bytes=10_000, connect_timeout_s=3, read_timeout_s=3, user_agent="test")


@pytest.fixture(scope="module")
def ca() -> trustme.CA:
    return trustme.CA()


@pytest.fixture
def tls_server(ca: trustme.CA) -> Iterator[int]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = f"host={self.headers.get('Host')}".encode()
            self.send_response(200)
            self.send_header("content-type", "text/plain")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ca.issue_cert(HOST).configure_cert(context)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def _fetcher(ca: trustme.CA, port: int) -> PinnedFetcher:
    def trusting() -> ssl.SSLContext:
        client_context = ssl.create_default_context()
        ca.configure_trust(client_context)
        return client_context

    return PinnedFetcher(
        dial=lambda ip, p: ("127.0.0.1", port) if ip == PUBLIC_IP else (ip, p),
        context_factory=trusting,
    )


def test_tls_connects_to_pinned_ip_and_verifies_hostname(ca: trustme.CA, tls_server: int) -> None:
    result = asyncio.run(_fetcher(ca, tls_server).fetch(f"https://{HOST}/", PUBLIC_IP, LIMITS))

    assert result.status == 200
    assert result.content == f"host={HOST}".encode()


def test_certificate_for_another_hostname_is_refused(ca: trustme.CA, tls_server: int) -> None:
    """Pinning the IP never weakens certificate checks: a name mismatch fails."""
    with pytest.raises(FetchError):
        asyncio.run(
            _fetcher(ca, tls_server).fetch("https://other.halden-bay.test/", PUBLIC_IP, LIMITS)
        )
