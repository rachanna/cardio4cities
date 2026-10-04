"""Fetch and parse robustness (BD-21; code review RV-011, RV-041, RV-042, RV-043, RV-109):
a page the parser cannot read is unreadable, never a crash; text is decoded as its
publisher wrote it; a dropped connection is tried once more; every official-API failure is
recorded with its reason. Local fictional web; AT-04 and AT-06 machinery unchanged."""

import pytest

from app.adapters.fetch.httpx_pinned import PinnedFetcher, _getaddrinfo, prefer_ipv4
from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser
from app.domain.vocab import CrawlOutcome, ParseOutcome
from app.ports.errors import FetchError
from app.ports.fetch import FetchLimits, FetchResult
from app.workflow.collection import Collector
from tests.support.webworld import (
    ALLOW_ALL,
    CountingBudget,
    Reply,
    WebWorld,
    article,
    collector,
    params,
)

HEALTH = "health.halden-bay.test"
DATA = "data.halden-bay.test"
HEALTH_IP, DATA_IP = "93.184.216.34", "151.101.1.69"
ACCENTED = "La prévalence de l'hypertension à Halden Bay était de 31,5 % en 2024."
BROKEN_PDF = b"%PDF-1.4\n1 0 obj << /Type /Catalog"  # cut off: no pages, no xref
FILLER = " Le service de santé de Halden Bay remercie toutes les familles participantes." * 6


@pytest.fixture
def world() -> WebWorld:
    return WebWorld()


def html(text: str, head: str = "") -> str:
    return (f"<html><head>{head}<title>Halden Bay</title></head><body><main><article>"
            f"<h1>Santé à Halden Bay</h1><p>{text}</p><p>{FILLER}</p></article></main>"
            "</body></html>")  # fmt: skip


def blank_pdf(pages: int) -> bytes:
    """A valid PDF whose pages carry no text: what a scanned report looks like to us."""
    kids = " ".join(f"{3 + n} 0 R" for n in range(pages))
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{kids}] /Count {pages} >>".encode(),
        *[b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] >>"] * pages,
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)


# --- RV-011: a page the parser cannot read ----------------------------------------------


async def test_a_malformed_pdf_is_unreadable_not_a_crash(world: WebWorld) -> None:
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": ALLOW_ALL,
        "/report.pdf": Reply(body=BROKEN_PDF, content_type="application/pdf"),
    })  # fmt: skip
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/report.pdf", [])
    assert result.outcome == "fetched"
    assert result.parse_outcome is ParseOutcome.UNREADABLE
    assert result.raw  # kept for the snapshot


async def test_a_scanned_pdf_with_no_text_is_unreadable(world: WebWorld) -> None:
    """RV-043: the parser's own page markers are not the document's text."""
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": ALLOW_ALL,
        "/scan.pdf": Reply(body=blank_pdf(40), content_type="application/pdf"),
    })  # fmt: skip
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/scan.pdf", [])
    assert result.document is not None
    assert result.document.text.count("[page ") == 40
    assert result.parse_outcome is ParseOutcome.UNREADABLE


# --- RV-042: charsets ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("body", "content_type"),
    [
        (html(ACCENTED).encode("latin-1"), "text/html; charset=ISO-8859-1"),
        (html(ACCENTED, '<meta charset="windows-1252">').encode("cp1252"), "text/html"),
        (html(ACCENTED, '<meta http-equiv="Content-Type" content="text/html; charset=iso-8859-1">')
         .encode("latin-1"), "text/html"),
        (html(ACCENTED).encode("cp1252"), "text/html"),  # undeclared, not valid UTF-8
        (html(ACCENTED).encode("utf-8"), "text/html"),  # undeclared UTF-8
        ((ACCENTED + FILLER).encode("latin-1"), "text/plain; charset=latin1"),
    ],
)  # fmt: skip
async def test_a_page_keeps_its_accents_whatever_its_charset(
    world: WebWorld, body: bytes, content_type: str
) -> None:
    page = Reply(body=body, content_type=content_type)
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/page": page})
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/page", [])
    assert result.document is not None
    assert "La prévalence de l'hypertension à Halden Bay" in result.document.text
    assert "�" not in result.document.text


# --- RV-041: one retry after a dropped connection -------------------------------------------


class Flaky(PinnedFetcher):
    """Fails the first `failures` content requests with `error`."""

    def __init__(self, world: WebWorld, error: FetchError, failures: int = 1) -> None:
        super().__init__(resolver=world.resolve, dial=world.dial)
        self.error, self.failures, self.calls = error, failures, 0

    async def fetch(self, url: str, pinned_ip: str, limits: FetchLimits,
                    intermediates: tuple[bytes, ...] = ()) -> FetchResult:  # fmt: skip
        if not url.endswith("/robots.txt"):
            self.calls += 1
            if self.calls <= self.failures:
                raise self.error
        return await super().fetch(url, pinned_ip, limits, intermediates)


def flaky_collector(fetcher: Flaky, slept: list[float]) -> Collector:
    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    return Collector(fetcher, ProtegoRobotsParser(), DocumentParser(), CountingBudget(),
                     params(), sleep=sleep)  # fmt: skip


async def test_a_dropped_connection_is_tried_once_more_after_a_second(world: WebWorld) -> None:
    world.site(
        HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/page": Reply(body=html(ACCENTED).encode())}
    )
    fetcher = Flaky(world, FetchError("network error: ConnectError", retryable=True))
    slept: list[float] = []
    with world.running():
        result = await flaky_collector(fetcher, slept).collect(f"http://{HEALTH}/page", [])
    assert result.parse_outcome is ParseOutcome.PARSED
    assert fetcher.calls == 2
    assert slept == [1.0]


async def test_a_timeout_or_second_failure_is_recorded_not_retried_again(world: WebWorld) -> None:
    world.site(
        HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/page": Reply(body=html(ACCENTED).encode())}
    )
    timeout = Flaky(world, FetchError("timeout: ReadTimeout", timeout=True))
    twice = Flaky(world, FetchError("network error: ConnectError", retryable=True), failures=2)
    slept: list[float] = []
    with world.running():
        first = await flaky_collector(timeout, slept).collect(f"http://{HEALTH}/page", [])
        second = await flaky_collector(twice, slept).collect(f"http://{HEALTH}/page", [])
    assert timeout.calls == 1  # a timeout already used its whole time
    assert first.final_decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert twice.calls == 2
    assert second.final_decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert "ConnectError" in second.final_decision.reason


# --- RV-011: host names IDNA cannot encode ------------------------------------------------


async def test_a_host_name_with_an_overlong_label_is_a_decision_not_a_crash() -> None:
    host = "a" * 64 + ".halden-bay.test"
    assert await _getaddrinfo(host) == []
    c = Collector(
        PinnedFetcher(), ProtegoRobotsParser(), DocumentParser(), CountingBudget(), params()
    )
    decision = await c.gate(f"http://{host}/page")
    assert decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK


# --- RV-109: official API failures ------------------------------------------------------------


@pytest.mark.parametrize(
    ("reply", "outcome"),
    [
        (Reply(401, b"{}", "application/json"), CrawlOutcome.BLOCKED_LOGIN_OR_PAYWALL),
        (Reply(403, b"{}", "application/json"), CrawlOutcome.BLOCKED_LOGIN_OR_PAYWALL),
        (Reply(503, b"{}", "application/json"), CrawlOutcome.UNREACHABLE_SERVER_ERROR),
        (Reply(429, b"{}", "application/json"), CrawlOutcome.RATE_LIMITED),
        (Reply(429, b"{}", "application/json", {"retry-after": "60"}), CrawlOutcome.RATE_LIMITED),
    ],
)
async def test_an_api_refusal_is_recorded_with_its_outcome(
    world: WebWorld, reply: Reply, outcome: CrawlOutcome
) -> None:
    world.site(DATA, DATA_IP, {"/api/indicator": reply})
    with world.running():
        got = await collector(world).fetch_api(f"http://{DATA}/api/indicator", "who_gho")
    assert got.result is None
    assert got.decisions[-1].outcome is outcome
    assert got.decisions[-1].rule == "api_terms:who_gho"
    assert world.paths(DATA) == ["/api/indicator"]  # no robots.txt: an API is under its terms


async def test_an_api_redirect_is_gated_again_and_followed(world: WebWorld) -> None:
    world.site(DATA, DATA_IP, {
        "/api/old": Reply(302, b"", None, {"location": "/api/new"}),
        "/api/new": Reply(200, b'{"value": []}', "application/json"),
    })  # fmt: skip
    with world.running():
        got = await collector(world).fetch_api(f"http://{DATA}/api/old", "who_gho")
    assert [d.outcome for d in got.decisions] == [CrawlOutcome.ALLOWED, CrawlOutcome.ALLOWED]
    assert got.result is not None
    assert got.result.content == b'{"value": []}'


async def test_an_api_answer_past_the_size_cap_is_not_used(world: WebWorld) -> None:
    world.site(
        DATA, DATA_IP, {"/api/big": Reply(200, b"[" + b"0," * 5000 + b"0]", "application/json")}
    )
    with world.running():
        got = await collector(world, max_bytes=1_000).fetch_api(f"http://{DATA}/api/big", "who_gho")
    assert (got.result, got.http_status) == (None, 200)


async def test_an_api_network_failure_is_unreachable(world: WebWorld) -> None:
    world.site(DATA, DATA_IP, {"/api/indicator": Reply(200, b"{}", "application/json")})
    fetcher = Flaky(world, FetchError("network error: ConnectError", retryable=True), failures=2)
    with world.running():
        c = Collector(fetcher, ProtegoRobotsParser(), DocumentParser(), CountingBudget(), params())
        got = await c.fetch_api(f"http://{DATA}/api/indicator", "who_gho")
    assert got.result is None
    assert got.decisions[-1].outcome is CrawlOutcome.UNREACHABLE_NETWORK


# --- a page whose server fails (BD-35) --------------------------------------------------------


@pytest.mark.parametrize(("status", "outcome"), [(503, "not_fetched"), (404, "http_error")])
async def test_a_server_error_makes_a_page_unreachable_and_a_missing_page_does_not(
    world: WebWorld, status: int, outcome: str
) -> None:
    """A 5xx page is unreachable, as robots.txt and an API are (LLD-2 §8), so the slot and
    the run summary count it; a 404 is a page that is not there, not an unreachable site."""
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/page": Reply(status, b"")})
    with world.running():
        got = await collector(world).collect(f"http://{HEALTH}/page", [])
    assert got.outcome == outcome
    expected = CrawlOutcome.UNREACHABLE_SERVER_ERROR if status >= 500 else CrawlOutcome.ALLOWED
    assert got.decisions[-1].outcome is expected


# --- RV-046: address order and the next checked address ---------------------------------------


def test_addresses_keep_the_resolver_order_with_ipv4_first() -> None:
    resolved = ["2001:db8::1", "93.184.216.34", "2001:db8::1", "151.101.1.69"]
    assert prefer_ipv4(resolved) == ["93.184.216.34", "151.101.1.69", "2001:db8::1"]


async def test_a_refused_connection_is_retried_at_the_host_s_next_address(world: WebWorld) -> None:
    """BD-36: one address of a host refuses; the one network retry dials the next."""
    dead = "93.184.216.99"
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/page": Reply(body=article())})
    world.dns[HEALTH] = [dead, HEALTH_IP]
    world.dead.add(dead)
    with world.running():
        got = await collector(world).collect(f"http://{HEALTH}/page", [])
    assert got.outcome == "fetched"
    assert got.decisions[0].pinned_ip == dead
    assert got.decisions[0].other_ips == (HEALTH_IP,)
    assert world.paths(HEALTH) == ["/robots.txt", "/page"]
