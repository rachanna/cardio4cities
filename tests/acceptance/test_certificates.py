"""Certificates (BD-15): a server that leaves out its intermediate certificate is read once
the collector fetches that certificate from the server certificate's own issuer (AIA) URL,
gated like every request; verification never relaxes. Expired, self-signed and mismatched
certificates stay refused, and every refusal names its cause in the crawl decision. A
certificate URL on a private address is refused before any request is made.

Local servers stand in for fictional Halden Bay hosts; the trust store holds a throwaway
root only."""

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
}


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
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), self.handler(routes))
        if tls is not None:
            server.socket = tls.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.ports[ip] = server.server_address[1]
        self.servers.append(server)

    servers: list[http.server.ThreadingHTTPServer] = field(default_factory=list)


@pytest.fixture
def ca() -> Authority:
    return authority()


@pytest.fixture
def net(ca: Authority, tmp_path: Path) -> Iterator[Net]:
    n = Net()
    pages = {"/robots.txt": b"User-agent: *\nAllow: /\n", "/page": article("Heart survey.")}
    foreign = authority()  # its root is not trusted
    n.serve(
        PKI_IP,
        {"/issuer.cer": der(ca.intermediate), "/foreign.cer": der(foreign.intermediate)},
        None,
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
    assert budget.reserved.count("certificate") == 1


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
