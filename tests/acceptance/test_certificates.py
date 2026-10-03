"""Certificates (BD-15): a server that leaves out its intermediate certificate is read once
the collector fetches that certificate from the server certificate's own issuer (AIA) URL,
gated like every request; verification never relaxes. Expired, self-signed and mismatched
certificates stay refused, and every refusal names its cause in the crawl decision. A
certificate URL on a private address is refused before any request is made.

Local servers stand in for fictional Halden Bay hosts; the trust store holds a throwaway
root only."""

import asyncio
import http.server
import ssl
import threading
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from app.adapters.fetch.httpx_pinned import PinnedFetcher
from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser
from app.domain.vocab import CrawlOutcome
from app.ports.errors import TLSCertificateError
from app.ports.fetch import FetchLimits
from app.workflow.collection import Collector
from tests.support.pki import Authority, authority, der
from tests.support.webworld import CountingBudget, article, params

PKI_HOST, PKI_IP = "pki.halden-bay.test", "93.184.216.51"
ISSUER_URL = f"http://{PKI_HOST}/issuer.cer"
PRIVATE_ISSUER_URL = "http://pki-internal.halden-bay.test/issuer.cer"
PRIVATE_IP = "10.0.0.7"
SITES = {  # host -> fictional public address
    "chain.halden-bay.test": "93.184.216.50",
    "privatechain.halden-bay.test": "93.184.216.52",
    "old.halden-bay.test": "93.184.216.53",
    "self.halden-bay.test": "93.184.216.54",
    "mismatch.halden-bay.test": "93.184.216.55",
    "foreign.halden-bay.test": "93.184.216.56",
    "rogue.halden-bay.test": "93.184.216.57",
}
ROGUE_ROOT_URL = f"http://{PKI_HOST}/rogue-root.cer"


@dataclass
class Net:
    ports: dict[str, int] = field(default_factory=dict)  # ip -> local port
    log: list[tuple[str, str]] = field(default_factory=list)  # (host header, path)

    def handler(self, body_for: dict[str, bytes]) -> type[http.server.BaseHTTPRequestHandler]:
        net = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                net.log.append((self.headers.get("Host", ""), self.path))
                body = body_for.get(self.path)
                self.send_response(200 if body is not None else 404)
                self.send_header("content-length", str(len(body or b"")))
                self.end_headers()
                self.wfile.write(body or b"")

            def log_message(self, *args: object) -> None:
                pass

        return Handler

    def serve(self, ip: str, routes: dict[str, bytes], tls: ssl.SSLContext | None) -> None:
        self.routes[ip] = routes
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self.handler(routes))
        if tls is not None:
            server.socket = tls.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.ports[ip] = server.server_address[1]
        self.servers.append(server)

    servers: list[http.server.ThreadingHTTPServer] = field(default_factory=list)
    routes: dict[str, dict[str, bytes]] = field(default_factory=dict)  # ip -> path -> body


@pytest.fixture
def ca() -> Authority:
    return authority()


@pytest.fixture
def net(ca: Authority, tmp_path: Path) -> Iterator[Net]:
    n = Net()
    pages = {"/robots.txt": b"User-agent: *\nAllow: /\n", "/page": article("Heart survey.")}
    foreign = authority()  # its root is not trusted
    rogue = authority()  # untrusted, with a root named exactly like the trusted one
    n.serve(
        PKI_IP,
        {
            "/issuer.cer": der(ca.intermediate),
            "/foreign.cer": der(foreign.intermediate),
            "/rogue-root.cer": der(rogue.root),
        },
        None,
    )
    n.serve(  # issued straight from an untrusted root, which its AIA URL serves (RV-001)
        SITES["rogue.halden-bay.test"],
        pages,
        rogue.server(tmp_path, "rogue.halden-bay.test", aia=ROGUE_ROOT_URL, by_root=True),
    )
    n.serve(
        SITES["foreign.halden-bay.test"],
        pages,
        foreign.server(tmp_path, "foreign.halden-bay.test", aia=f"http://{PKI_HOST}/foreign.cer"),
    )
    n.serve(
        SITES["chain.halden-bay.test"],
        pages,
        ca.server(tmp_path, "chain.halden-bay.test", aia=ISSUER_URL),
    )
    n.serve(
        SITES["privatechain.halden-bay.test"],
        pages,
        ca.server(tmp_path, "privatechain.halden-bay.test", aia=PRIVATE_ISSUER_URL),
    )
    n.serve(
        SITES["old.halden-bay.test"],
        pages,
        ca.server(tmp_path, "old.halden-bay.test", expired=True, chain=True),
    )
    n.serve(
        SITES["self.halden-bay.test"],
        pages,
        ca.server(tmp_path, "self.halden-bay.test", self_signed=True),
    )
    n.serve(SITES["mismatch.halden-bay.test"], pages,
            ca.server(tmp_path, "other.halden-bay.test", chain=True))  # fmt: skip
    n.ports[PRIVATE_IP] = n.ports[PKI_IP]  # were it ever dialled, the log would show it
    yield n
    for server in n.servers:
        server.shutdown()
        server.server_close()


def collector(ca: Authority, net: Net, budget: CountingBudget) -> Collector:
    addresses = {**SITES, PKI_HOST: PKI_IP, "pki-internal.halden-bay.test": PRIVATE_IP}

    async def resolve(host: str) -> list[str]:
        return [addresses[host]] if host in addresses else []

    fetcher = PinnedFetcher(
        resolver=resolve,
        dial=lambda ip, port: ("127.0.0.1", net.ports[ip]),
        context_factory=ca.trusting,
        trusted_roots=lambda: [ca.root],
    )
    return Collector(fetcher, ProtegoRobotsParser(), DocumentParser(), budget, params())


async def test_a_missing_intermediate_is_fetched_from_aia_and_the_page_is_read(
    ca: Authority, net: Net
) -> None:
    budget = CountingBudget()
    collected = await collector(ca, net, budget).collect("https://chain.halden-bay.test/page", [])
    assert collected.outcome == "fetched"
    assert collected.final_decision.outcome is CrawlOutcome.ALLOWED
    assert net.log.count((PKI_HOST, "/issuer.cer")) == 1  # once per run, then cached
    assert budget.reserved.count("certificate") == 2  # the download, then the chain check


async def test_a_private_address_certificate_url_is_refused_unrequested(
    ca: Authority, net: Net
) -> None:
    budget = CountingBudget()
    url = "https://privatechain.halden-bay.test/page"
    collected = await collector(ca, net, budget).collect(url, [])
    decision = collected.decisions[0]
    assert decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert "chain is incomplete" in decision.reason
    assert "issuer certificate URL was refused" in decision.reason
    assert [path for _, path in net.log if path == "/issuer.cer"] == []  # never requested
    assert "certificate" not in budget.reserved


@pytest.mark.parametrize(
    ("host", "cause"),
    [
        ("old.halden-bay.test", "TLS certificate has expired"),
        ("self.halden-bay.test", "TLS certificate is self-signed"),
        ("mismatch.halden-bay.test", "TLS certificate does not match the host name"),
    ],
)
async def test_bad_certificates_stay_refused_and_name_their_cause(
    ca: Authority, net: Net, host: str, cause: str
) -> None:
    collected = await collector(ca, net, CountingBudget()).collect(f"https://{host}/page", [])
    decision = collected.decisions[0]
    assert collected.outcome == "not_fetched"
    assert decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert f"robots.txt could not be reached ({cause})" in decision.reason
    assert [path for h, path in net.log if h.startswith(host)] == []  # TLS stopped it


async def test_a_fetched_intermediate_is_never_a_trust_anchor(ca: Authority, net: Net) -> None:
    """The chain must still end at a trusted root: an intermediate from an untrusted
    authority, fetched from the AIA URL, does not make its certificates trusted."""
    collected = await collector(ca, net, CountingBudget()).collect(
        "https://foreign.halden-bay.test/page", []
    )
    decision = collected.decisions[0]
    assert collected.outcome == "not_fetched"
    assert decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert "TLS certificate" in decision.reason
    assert (PKI_HOST, "/foreign.cer") in net.log  # fetched, and still not trusted


async def test_a_self_signed_root_served_at_an_aia_url_is_never_trusted(
    ca: Authority, net: Net
) -> None:
    """RV-001 (BD-16): a site certificate issued straight from an untrusted root, whose AIA
    URL serves that self-signed root (named like the trusted one), stays refused. The
    fetched certificate is an untrusted intermediate; only the trusted roots anchor."""
    collected = await collector(ca, net, CountingBudget()).collect(
        "https://rogue.halden-bay.test/page", []
    )
    decision = collected.decisions[0]
    assert (PKI_HOST, "/rogue-root.cer") in net.log  # fetched, and still not trusted
    assert collected.outcome == "not_fetched"
    assert decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert "chain could not be completed to a trusted root" in decision.reason
    assert [path for h, path in net.log if h.startswith("rogue.")] == []  # nothing read


async def test_a_self_signed_certificate_handed_to_the_fetcher_is_never_added(
    ca: Authority, net: Net
) -> None:
    """Belt and braces: even if a self-signed root reached `fetch` as an intermediate, it
    is never loaded into the TLS context, so the connection stays refused."""
    fetcher = PinnedFetcher(
        dial=lambda ip, port: ("127.0.0.1", net.ports[ip]),
        context_factory=ca.trusting,
        trusted_roots=lambda: [ca.root],
    )
    limits = FetchLimits(max_bytes=100_000, connect_timeout_s=3, read_timeout_s=3,
                         user_agent="test")  # fmt: skip
    with pytest.raises(TLSCertificateError):
        await fetcher.fetch(
            "https://rogue.halden-bay.test/page",
            SITES["rogue.halden-bay.test"],
            limits,
            (net.routes[PKI_IP]["/rogue-root.cer"],),
        )


async def test_two_requests_completing_one_chain_download_and_verify_it_once(
    ca: Authority, net: Net
) -> None:
    """RV-078: the issuer certificate is downloaded, and the chain verified, once per run
    even when two requests need it at the same moment."""
    budget = CountingBudget()
    shared = collector(ca, net, budget)
    first, second = await asyncio.gather(
        shared.collect("https://chain.halden-bay.test/page", []),
        shared.collect("https://chain.halden-bay.test/other", []),
    )
    assert first.outcome == "fetched"
    assert second.final_decision.outcome is CrawlOutcome.ALLOWED
    assert net.log.count((PKI_HOST, "/issuer.cer")) == 1
    assert budget.reserved.count("certificate") == 2
