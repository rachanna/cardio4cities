"""Crawl gate and fetching against a local fictional web (LLD-2 §9; AT-04, AT-05, AT-06,
AT-23; AT-33 is in tests/contract/test_search_adapters.py)."""

import time
from collections.abc import Iterator
from itertools import pairwise

import pytest

from app.domain.vocab import CrawlOutcome, ParseOutcome, SourceKind
from app.workflow.rules.selection import publisher_table, select_urls
from tests.support.webworld import (
    ALLOW_ALL,
    CountingBudget,
    Reply,
    WebWorld,
    article,
    collector,
)

HEALTH = "health.halden-bay.test"
NEWS = "news.halden-bay.test"
HEALTH_IP, NEWS_IP = "93.184.216.34", "151.101.1.69"


@pytest.fixture
def world() -> Iterator[WebWorld]:
    with WebWorld().running() as w:
        yield w


# --- AT-04 robots.txt -----------------------------------------------------------------


async def test_disallowed_url_gets_no_content_request(world: WebWorld) -> None:
    """AT-04: given a URL disallowed by robots.txt, zero content requests are made to it,
    and the decision and reason are recorded."""
    robots = Reply(200, b"User-agent: *\nDisallow: /reports/\n", "text/plain")
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": robots, "/reports/2024": Reply(body=article())})

    result = await collector(world).collect(f"http://{HEALTH}/reports/2024", [])

    assert world.paths(HEALTH) == ["/robots.txt"]  # no content request
    decision = result.final_decision
    assert decision.outcome is CrawlOutcome.BLOCKED_ROBOTS
    assert decision.rule == "Disallow: /reports/"
    assert "robots.txt disallows" in decision.reason
    assert result.outcome == "not_fetched"
    assert result.raw == b""


async def test_robots_is_fetched_once_per_origin(world: WebWorld) -> None:
    pages = {f"/p{n}": Reply(body=article()) for n in range(3)}
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, **pages})
    c = collector(world)

    for n in range(3):
        await c.collect(f"http://{HEALTH}/p{n}", [])

    assert world.paths(HEALTH).count("/robots.txt") == 1


async def test_missing_robots_means_no_restrictions(world: WebWorld) -> None:
    world.site(HEALTH, HEALTH_IP, {"/page": Reply(body=article())})  # /robots.txt -> 404

    result = await collector(world).collect(f"http://{HEALTH}/page", [])

    assert result.outcome == "fetched"
    assert result.final_decision.robots_http_status == 404


async def test_robots_server_error_treats_site_as_unreachable(world: WebWorld) -> None:
    """RFC 9309: 5xx means complete disallow, reported as unreachable, not blocked (WD-07)."""
    world.site(
        HEALTH,
        HEALTH_IP,
        {"/robots.txt": Reply(503, b"busy", "text/plain"), "/page": Reply(body=article())},
    )

    result = await collector(world).collect(f"http://{HEALTH}/page", [])

    assert result.final_decision.outcome is CrawlOutcome.UNREACHABLE_SERVER_ERROR
    assert world.paths(HEALTH) == ["/robots.txt"]


async def test_content_usage_in_robots_blocks_before_any_content_request(world: WebWorld) -> None:
    robots = Reply(200, b"User-agent: *\nAllow: /\nContent-Usage: ai-use=n\n", "text/plain")
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": robots, "/page": Reply(body=article())})

    result = await collector(world).collect(f"http://{HEALTH}/page", [])

    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_CONTENT_USAGE
    assert world.paths(HEALTH) == ["/robots.txt"]


async def test_train_ai_opt_out_is_recorded_not_blocking(world: WebWorld) -> None:
    robots = Reply(200, b"User-agent: *\nAllow: /\nContent-Usage: train-ai=n\n", "text/plain")
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": robots, "/page": Reply(body=article())})

    result = await collector(world).collect(f"http://{HEALTH}/page", [])

    assert result.outcome == "fetched"
    assert result.final_decision.usage_preferences == {"train-ai": "n"}


# --- AT-05 crawl-delay ---------------------------------------------------------------


async def test_requests_are_spaced_by_crawl_delay(world: WebWorld) -> None:
    """AT-05: given crawl-delay N, requests to the site are at least N seconds apart."""
    robots = Reply(200, b"User-agent: *\nCrawl-delay: 1\nAllow: /\n", "text/plain")
    world.site(
        HEALTH,
        HEALTH_IP,
        {"/robots.txt": robots, **{f"/p{n}": Reply(body=article()) for n in range(3)}},
    )
    c = collector(world)

    for n in range(3):
        await c.collect(f"http://{HEALTH}/p{n}", [])

    times = [h.at for h in world.log if h.host == HEALTH and h.path.startswith("/p")]
    assert len(times) == 3
    assert all(later - earlier >= 0.95 for earlier, later in pairwise(times))


async def test_min_interval_applies_without_crawl_delay(world: WebWorld) -> None:
    world.site(
        HEALTH,
        HEALTH_IP,
        {"/robots.txt": ALLOW_ALL, "/a": Reply(body=article()), "/b": Reply(body=article())},
    )
    c = collector(world, min_interval_s=0.5)

    await c.collect(f"http://{HEALTH}/a", [])
    await c.collect(f"http://{HEALTH}/b", [])

    a, b = (h.at for h in world.log if h.path in ("/a", "/b"))
    assert b - a >= 0.45


# --- AT-06 content only through the gate ----------------------------------------------


async def test_content_enters_only_through_gate_and_snippets_are_never_evidence(
    world: WebWorld,
) -> None:
    """AT-06: content extraction passes the crawl gate first; a search hit contributes only
    its URL, so its snippet can never become evidence."""
    world.site(
        HEALTH,
        HEALTH_IP,
        {
            "/robots.txt": Reply(200, b"User-agent: *\nDisallow: /\n", "text/plain"),
            "/page": Reply(body=article("31.2% of adults")),
        },
    )
    table = publisher_table({"deny": {"domains": []}, "classes": {}})
    hit_url, snippet = f"http://{HEALTH}/page", "In Halden Bay, 99% of adults had hypertension."

    (chosen,) = select_urls([(hit_url, 1)], set(), table, max_new=4)
    result = await collector(world).collect(chosen.url, [])

    assert not hasattr(chosen, "snippet")  # selection keeps the URL only
    assert result.document is None
    assert snippet.encode() not in result.raw
    assert world.paths(HEALTH) == ["/robots.txt"]


async def test_every_request_reserves_budget_first(world: WebWorld) -> None:
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/page": Reply(body=article())})
    budget = CountingBudget()

    await collector(world, budget).collect(f"http://{HEALTH}/page", [])

    assert budget.reserved == ["robots", "fetch"]
    assert len(world.log) == 2


# --- AT-23 private addresses ---------------------------------------------------------


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "192.168.1.20",
        "169.254.169.254",
        "100.100.100.200",
        "::1",
        "fd00:ec2::254",
        "::ffff:127.0.0.1",
        "0.0.0.0",  # noqa: S104 (an address under test, not a bind)
    ],
)
async def test_private_loopback_and_metadata_addresses_are_refused(
    world: WebWorld, address: str
) -> None:
    """AT-23: given a URL resolving to a private, loopback or metadata address, the fetch
    is refused before any request."""
    world.site("internal.halden-bay.test", address, {"/": Reply(body=article())})

    result = await collector(world).collect("http://internal.halden-bay.test/", [])

    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_PRIVATE_ADDRESS
    assert world.log == []


async def test_host_with_any_private_address_is_refused(world: WebWorld) -> None:
    world.site(HEALTH, HEALTH_IP, {"/": Reply(body=article())})
    world.dns[HEALTH] = [HEALTH_IP, "10.1.2.3"]

    result = await collector(world).collect(f"http://{HEALTH}/", [])

    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_PRIVATE_ADDRESS
    assert world.log == []


async def test_redirect_to_a_private_host_is_refused(world: WebWorld) -> None:
    """AT-23: every redirect hop goes back through the gate."""
    world.site(
        HEALTH,
        HEALTH_IP,
        {
            "/robots.txt": ALLOW_ALL,
            "/go": Reply(302, b"", None, {"location": "http://admin.halden-bay.test/x"}),
        },
    )
    world.site("admin.halden-bay.test", "10.0.0.9", {"/x": Reply(body=article())})

    result = await collector(world).collect(f"http://{HEALTH}/go", [])

    assert [d.outcome for d in result.decisions] == [
        CrawlOutcome.ALLOWED,
        CrawlOutcome.BLOCKED_PRIVATE_ADDRESS,
    ]
    assert world.paths("admin.halden-bay.test") == []


async def test_redirect_to_a_literal_loopback_url_is_refused(world: WebWorld) -> None:
    world.site(
        HEALTH,
        HEALTH_IP,
        {
            "/robots.txt": ALLOW_ALL,
            "/go": Reply(301, b"", None, {"location": "http://127.0.0.1/secret"}),
        },
    )

    result = await collector(world).collect(f"http://{HEALTH}/go", [])

    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_PRIVATE_ADDRESS


async def test_redirect_to_a_new_host_checks_that_hosts_robots(world: WebWorld) -> None:
    world.site(
        HEALTH,
        HEALTH_IP,
        {
            "/robots.txt": ALLOW_ALL,
            "/go": Reply(302, b"", None, {"location": f"http://{NEWS}/story"}),
        },
    )
    world.site(
        NEWS,
        NEWS_IP,
        {
            "/robots.txt": Reply(200, b"User-agent: *\nDisallow: /story\n", "text/plain"),
            "/story": Reply(body=article()),
        },
    )

    result = await collector(world).collect(f"http://{HEALTH}/go", [])

    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_ROBOTS
    assert world.paths(NEWS) == ["/robots.txt"]


async def test_dns_rebinding_cannot_move_the_connection(world: WebWorld) -> None:
    """The fetcher dials the address the gate checked; a later DNS answer is never used."""
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/page": Reply(body=article())})
    answers = iter([[HEALTH_IP], ["127.0.0.1"], ["127.0.0.1"]])

    async def rebinding(host: str) -> list[str]:
        return next(answers)

    c = collector(world)
    c._fetcher._resolver = rebinding  # type: ignore[attr-defined]

    result = await c.collect(f"http://{HEALTH}/page", [])

    assert result.outcome == "fetched"
    assert result.final_decision.pinned_ip == HEALTH_IP


async def test_unsupported_port_is_refused(world: WebWorld) -> None:
    result = await collector(world).collect(f"http://{HEALTH}:8080/page", [])

    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_PRIVATE_ADDRESS
    assert "port" in result.final_decision.reason


# --- fetch rules (§9.3) and parsing (§9.4) ----------------------------------------------


@pytest.mark.parametrize("status", [401, 402, 403])
async def test_login_or_paywall_status_discards_the_body(world: WebWorld, status: int) -> None:
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/p": Reply(status, article())})

    result = await collector(world).collect(f"http://{HEALTH}/p", [])

    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_LOGIN_OR_PAYWALL
    assert (result.raw, result.document) == (b"", None)


async def test_content_usage_header_discards_the_body(world: WebWorld) -> None:
    page = Reply(body=article(), headers={"content-usage": "ai-use=n"})
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/p": page})

    result = await collector(world).collect(f"http://{HEALTH}/p", [])

    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_CONTENT_USAGE
    assert result.raw == b""


async def test_429_with_short_retry_after_is_retried_once(world: WebWorld) -> None:
    replies = iter([Reply(429, b"", "text/plain", {"retry-after": "1"}), Reply(body=article())])
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/p": lambda: next(replies)})
    started = time.monotonic()

    result = await collector(world).collect(f"http://{HEALTH}/p", [])

    assert result.outcome == "fetched"
    assert time.monotonic() - started >= 0.95
    assert world.paths(HEALTH).count("/p") == 2


async def test_429_with_long_retry_after_is_rate_limited(world: WebWorld) -> None:
    page = Reply(429, b"", "text/plain", {"retry-after": "120"})
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/p": page})

    result = await collector(world).collect(f"http://{HEALTH}/p", [])

    assert result.final_decision.outcome is CrawlOutcome.RATE_LIMITED
    assert world.paths(HEALTH).count("/p") == 1


async def test_too_large_is_recorded_without_a_snapshot(world: WebWorld) -> None:
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/big": Reply(body=b"x" * 5000)})

    result = await collector(world, max_bytes=1000).collect(f"http://{HEALTH}/big", [])

    assert (result.parse_outcome, result.raw) == (ParseOutcome.TOO_LARGE, b"")


async def test_unsupported_type_is_recorded_without_parsing(world: WebWorld) -> None:
    sheet = Reply(body=b"PK\x03\x04", content_type="application/vnd.ms-excel")
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/sheet": sheet})

    result = await collector(world).collect(f"http://{HEALTH}/sheet", [])

    assert result.parse_outcome is ParseOutcome.UNSUPPORTED_TYPE
    assert result.document is None


async def test_short_page_is_unreadable_but_kept(world: WebWorld) -> None:
    world.site(
        HEALTH,
        HEALTH_IP,
        {
            "/robots.txt": ALLOW_ALL,
            "/short": Reply(body=b"<html><body><p>Coming soon.</p></body></html>"),
        },
    )

    result = await collector(world).collect(f"http://{HEALTH}/short", [])

    assert result.parse_outcome is ParseOutcome.UNREADABLE
    assert result.raw != b""


async def test_login_form_page_is_blocked(world: WebWorld) -> None:
    form = (
        b'<html><body><form><input name="u"><input type="password" name="p"></form></body></html>'
    )
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/login": Reply(body=form)})

    result = await collector(world).collect(f"http://{HEALTH}/login", [])

    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_LOGIN_OR_PAYWALL


async def test_readable_html_page_is_parsed_with_its_tables(world: WebWorld) -> None:
    body = article("In Halden Bay, 31.2% of adults had raised blood pressure.").replace(
        b"</article>",
        b"<table><tr><th>Indicator</th><th>Value</th></tr>"
        b"<tr><td>Raised BP</td><td>31.2%</td></tr></table></article>",
    )
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/page": Reply(body=body)})

    result = await collector(world).collect(f"http://{HEALTH}/page?utm_source=x", [])

    assert result.final_url == f"http://{HEALTH}/page"  # tracking parameter dropped
    assert (result.kind, result.parse_outcome) == (SourceKind.WEB_HTML, ParseOutcome.PARSED)
    assert result.document is not None
    assert "31.2% of adults" in result.document.text
    assert len(result.document.tables) == 1


async def test_a_server_that_never_answers_is_unreachable_not_a_crash(world: WebWorld) -> None:
    """Found by spike S-5: httpcore timeouts must surface as FetchError (BD-07)."""

    def hang() -> Reply:
        time.sleep(2.5)
        return Reply(body=article())

    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/slow": hang})

    result = await collector(world, read_timeout_s=0.5).collect(f"http://{HEALTH}/slow", [])

    assert result.final_decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert "timeout" in result.final_decision.reason


async def test_pdf_sent_as_octet_stream_is_recognised_by_its_signature(world: WebWorld) -> None:
    """Found by spike S-5: some repositories label PDFs application/octet-stream."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.set_font("Helvetica", size=11)
    pdf.add_page()
    pdf.multi_cell(0, 6, "Hypertension in Halden Bay. " * 20)
    page = Reply(body=bytes(pdf.output()), content_type="application/octet-stream")
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/report": page})

    result = await collector(world).collect(f"http://{HEALTH}/report", ["hypertension"])

    assert (result.kind, result.parse_outcome) == (SourceKind.WEB_PDF, ParseOutcome.PARSED)


async def test_unknown_binary_is_still_unsupported(world: WebWorld) -> None:
    page = Reply(body=b"\x89PNG\r\n", content_type="application/octet-stream")
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/image": page})

    result = await collector(world).collect(f"http://{HEALTH}/image", [])

    assert result.parse_outcome is ParseOutcome.UNSUPPORTED_TYPE
