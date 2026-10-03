"""Crawl gate correctness (BD-20; code review RV-009, RV-045, RV-013, RV-012): robots.txt
read as served, sites that answer robots.txt badly are unreachable, waiting for a site
can never outlast the run or stall other sites, and a compressed body can never inflate
past the size cap. Local fictional web; AT-04 and AT-05 are the requirements at stake."""

import asyncio
import gzip
import time
import zlib

import pytest

from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser
from app.domain.vocab import CrawlOutcome, ParseOutcome
from app.ports.fetch import FetchLimits
from app.workflow.collection import Collector, FetchKind
from app.workflow.rules.robots import ROBOTS_MAX_BYTES
from tests.support.webworld import (
    ALLOW_ALL,
    UA,
    CountingBudget,
    Reply,
    WebWorld,
    article,
    collector,
    params,
)

HEALTH = "health.halden-bay.test"
NEWS = "news.halden-bay.test"
HEALTH_IP, NEWS_IP = "93.184.216.34", "151.101.1.69"
BOM = "﻿".encode()


@pytest.fixture
def world() -> WebWorld:
    return WebWorld()


def robots(text: bytes) -> Reply:
    return Reply(200, text, "text/plain")


# --- RV-009: a byte order mark -----------------------------------------------------------


async def test_robots_with_a_byte_order_mark_still_disallows(world: WebWorld) -> None:
    """AT-04: the first group is read even when the file starts with a BOM."""
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": robots(BOM + b"User-agent: *\nDisallow: /\n"),
        "/page": Reply(body=article()),
    })  # fmt: skip
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/page", [])
    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_ROBOTS
    assert world.paths(HEALTH) == ["/robots.txt"]


async def test_a_content_usage_opt_out_after_a_byte_order_mark_still_blocks(
    world: WebWorld,
) -> None:
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": robots(BOM + b"User-agent: *\nContent-Usage: ai=n\nAllow: /\n"),
        "/page": Reply(body=article()),
    })  # fmt: skip
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/page", [])
    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_CONTENT_USAGE
    assert world.paths(HEALTH) == ["/robots.txt"]


async def test_a_robots_file_past_the_parse_limit_is_still_applied(world: WebWorld) -> None:
    """RFC 9309 §2.5: the first 500 KiB is parsed; a longer file is not "no robots.txt"."""
    padding = b"# padding\n" * (ROBOTS_MAX_BYTES // 10 + 100)
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": robots(b"User-agent: *\nDisallow: /\n" + padding),
        "/page": Reply(body=article()),
    })  # fmt: skip
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/page", [])
    assert result.final_decision.outcome is CrawlOutcome.BLOCKED_ROBOTS
    assert world.paths(HEALTH) == ["/robots.txt"]


# --- RV-045: robots.txt answered badly -------------------------------------------------------


async def test_robots_answering_429_makes_the_site_unreachable(world: WebWorld) -> None:
    """Owner decision: too many requests is not "no robots.txt"; nothing is fetched."""
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": Reply(429, b"slow down", "text/plain"),
        "/page": Reply(body=article()),
    })  # fmt: skip
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/page", [])
    decision = result.final_decision
    assert decision.outcome is CrawlOutcome.UNREACHABLE_SERVER_ERROR
    assert "429" in decision.reason
    assert world.paths(HEALTH) == ["/robots.txt"]


async def test_robots_redirecting_where_we_never_dial_makes_the_site_unreachable(
    world: WebWorld,
) -> None:
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": Reply(301, b"", None, {"location": f"http://{HEALTH}:8081/robots.txt"}),
        "/page": Reply(body=article()),
    })  # fmt: skip
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/page", [])
    decision = result.final_decision
    assert decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert "redirects where we never dial" in decision.reason
    assert world.paths(HEALTH) == ["/robots.txt"]


# --- RV-013: waiting for a site ----------------------------------------------------------------


async def test_a_crawl_delay_past_the_cap_is_rate_limited_without_a_request(
    world: WebWorld,
) -> None:
    """Owner decision: a crawl-delay above 30 s is recorded, never waited out."""
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": robots(b"User-agent: *\nCrawl-delay: 3600\nAllow: /\n"),
        "/page": Reply(body=article()),
    })  # fmt: skip
    started = time.monotonic()
    with world.running():
        result = await collector(world, crawl_delay_cap_s=30.0).collect(f"http://{HEALTH}/page", [])
    decision = result.final_decision
    assert decision.outcome is CrawlOutcome.RATE_LIMITED
    assert decision.rule == "Crawl-delay: 3600"
    assert world.paths(HEALTH) == ["/robots.txt"]
    assert time.monotonic() - started < 5


async def test_a_wait_past_the_runs_time_left_is_rate_limited_and_reserves_nothing(
    world: WebWorld,
) -> None:
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": robots(b"User-agent: *\nCrawl-delay: 5\nAllow: /\n"),
        "/page": Reply(body=article()),
    })  # fmt: skip
    budget = CountingBudget(time_left_s=2.0)
    started = time.monotonic()
    with world.running():
        result = await collector(world, budget).collect(f"http://{HEALTH}/page", [])
    decision = result.final_decision
    assert decision.outcome is CrawlOutcome.RATE_LIMITED
    assert "time left" in decision.reason
    assert budget.reserved == ["robots"]  # the page was never reserved or requested
    assert world.paths(HEALTH) == ["/robots.txt"]
    assert time.monotonic() - started < 2


class RefusingBudget(CountingBudget):
    async def reserve(self, kind: FetchKind) -> None:
        if kind == "fetch":
            raise RuntimeError("budget spent")
        await super().reserve(kind)


async def test_the_budget_is_reserved_before_any_wait(world: WebWorld) -> None:
    """Past the wind-down a reservation is refused: the run must not sleep first."""
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": robots(b"User-agent: *\nCrawl-delay: 20\nAllow: /\n"),
        "/page": Reply(body=article()),
    })  # fmt: skip
    slept: list[float] = []

    async def sleep(seconds: float) -> None:
        slept.append(seconds)

    with world.running():
        c = Collector(world.fetcher(), ProtegoRobotsParser(), DocumentParser(),
                      RefusingBudget(), params(), sleep=sleep)  # fmt: skip
        with pytest.raises(RuntimeError, match="budget spent"):
            await c.collect(f"http://{HEALTH}/page", [])
    assert slept == []


async def test_a_slow_site_never_holds_the_permits_other_sites_need(world: WebWorld) -> None:
    """One global permit: while one site's next page waits out its crawl-delay, another
    site is fetched at once."""
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": robots(b"User-agent: *\nCrawl-delay: 2\nAllow: /\n"),
        "/a": Reply(body=article()),
        "/b": Reply(body=article()),
    })  # fmt: skip
    world.site(NEWS, NEWS_IP, {"/robots.txt": ALLOW_ALL, "/n": Reply(body=article())})
    with world.running():
        c = collector(world, concurrency=1)
        await c.collect(f"http://{HEALTH}/a", [])
        started = time.monotonic()
        slow = asyncio.create_task(c.collect(f"http://{HEALTH}/b", []))
        await asyncio.sleep(0.1)  # the slow page is now waiting
        await c.collect(f"http://{NEWS}/n", [])
        other_done = time.monotonic() - started
        await slow
    assert other_done < 1.0  # not 2 s behind the slow site
    times = {h.path: h.at for h in world.log}
    assert times["/b"] - times["/a"] >= 1.95  # the slow site's spacing still holds


# --- RV-012: compressed bodies -----------------------------------------------------------------


def limits(max_bytes: int, keep_partial: bool = False) -> FetchLimits:
    return FetchLimits(max_bytes=max_bytes, connect_timeout_s=3, read_timeout_s=3,
                       user_agent=UA, keep_partial=keep_partial)  # fmt: skip


async def test_a_gzip_bomb_stops_at_the_cap_on_decoded_bytes(world: WebWorld) -> None:
    bomb = gzip.compress(b"\0" * 40_000_000)
    assert len(bomb) < 100_000
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": ALLOW_ALL,
        "/bomb": Reply(body=bomb, headers={"content-encoding": "gzip"}),
    })  # fmt: skip
    with world.running():
        fetched = await world.fetcher().fetch(f"http://{HEALTH}/bomb", HEALTH_IP, limits(1_000_000))
        result = await collector(world, max_bytes=1_000_000).collect(f"http://{HEALTH}/bomb", [])
    assert fetched.truncated
    assert fetched.content == b""
    assert result.parse_outcome is ParseOutcome.TOO_LARGE


async def test_compressed_pages_within_the_cap_are_decoded(world: WebWorld) -> None:
    page = article("Halden Bay reported on heart health.")
    raw_deflate = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    world.site(HEALTH, HEALTH_IP, {
        "/gz": Reply(body=gzip.compress(page), headers={"content-encoding": "gzip"}),
        "/zl": Reply(body=zlib.compress(page), headers={"content-encoding": "deflate"}),
        "/raw": Reply(body=raw_deflate.compress(page) + raw_deflate.flush(),
                      headers={"content-encoding": "deflate"}),
    })  # fmt: skip
    with world.running():
        fetcher = world.fetcher()
        for path in ("/gz", "/zl", "/raw"):
            got = await fetcher.fetch(f"http://{HEALTH}{path}", HEALTH_IP, limits(1_000_000))
            assert (got.content, got.truncated) == (page, False), path


async def test_keep_partial_keeps_the_first_bytes_decoded(world: WebWorld) -> None:
    body = b"x" * 5_000
    world.site(HEALTH, HEALTH_IP, {
        "/big": Reply(body=gzip.compress(body), headers={"content-encoding": "gzip"}),
    })  # fmt: skip
    with world.running():
        got = await world.fetcher().fetch(f"http://{HEALTH}/big", HEALTH_IP, limits(1_000, True))
    assert got.truncated
    assert got.content == body[:1_000]


async def test_an_encoding_we_did_not_ask_for_is_refused_unread(world: WebWorld) -> None:
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": ALLOW_ALL,
        "/br": Reply(body=b"\x8b\x02\x80", headers={"content-encoding": "br"}),
    })  # fmt: skip
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/br", [])
    decision = result.final_decision
    assert decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert "unsupported content encoding" in decision.reason
