"""The event loop and downloads (BD-27; code review RV-047, RV-048, RV-097, RV-098): a
download is bounded as a whole and never outlives the run, a body declared too large is
refused unread, a PDF is read up to its page cap, a window is normalised once, and Wave 0
runs alongside planning. Local fictional web."""

import time

from app.adapters.parse.documents import DocumentParser
from app.domain.params import QuoteParams
from app.domain.vocab import CrawlOutcome, ParseOutcome
from app.ports.fetch import FetchLimits
from app.workflow.graph import build_graph
from app.workflow.rules.quotes import match_quote, normalise
from tests.acceptance.test_fetch_robustness import blank_pdf, html
from tests.support.webworld import ALLOW_ALL, UA, CountingBudget, Reply, WebWorld, collector

HEALTH, HEALTH_IP = "health.halden-bay.test", "93.184.216.34"


def slow(seconds: float, body: bytes) -> Reply:
    time.sleep(seconds)
    return Reply(body=body)


async def test_a_download_is_bounded_as_a_whole() -> None:
    """RV-047: only each read had a timeout, so a slow large file streamed on."""
    world = WebWorld()
    page = html("Halden Bay reported on heart health.").encode()
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/slow": lambda: slow(3.0, page)})
    started = time.monotonic()
    with world.running():
        result = await collector(world, total_timeout_s=1.0).collect(f"http://{HEALTH}/slow", [])
    decision = result.final_decision
    assert decision.outcome is CrawlOutcome.UNREACHABLE_NETWORK
    assert "took longer than 1 s" in decision.reason
    assert time.monotonic() - started < 2.9


async def test_a_download_never_outlives_the_run() -> None:
    world = WebWorld()
    page = html("Halden Bay reported on heart health.").encode()
    world.site(HEALTH, HEALTH_IP, {"/robots.txt": ALLOW_ALL, "/slow": lambda: slow(3.0, page)})
    with world.running():
        c = collector(world, CountingBudget(time_left_s=0.2), total_timeout_s=60.0)
        result = await c.collect(f"http://{HEALTH}/slow", [])
    assert "took longer than 1 s" in result.final_decision.reason  # at least 1 s is allowed


async def test_a_body_declared_too_large_is_refused_unread() -> None:
    world = WebWorld()
    world.site(HEALTH, HEALTH_IP, {"/big": Reply(body=b"x" * 50_000)})
    limits = FetchLimits(max_bytes=1_000, connect_timeout_s=3, read_timeout_s=3, user_agent=UA)
    with world.running():
        got = await world.fetcher().fetch(f"http://{HEALTH}/big", HEALTH_IP, limits)
        partial = await world.fetcher().fetch(
            f"http://{HEALTH}/big", HEALTH_IP, limits.model_copy(update={"keep_partial": True})
        )
    assert (got.truncated, got.content) == (True, b"")
    assert partial.truncated
    assert partial.content == b"x" * 1_000  # robots.txt still keeps its first bytes


async def test_a_large_pdf_page_is_parsed_off_the_event_loop_and_up_to_the_cap() -> None:
    """RV-048: parsing ran on the loop; a page cap bounds the work."""
    world = WebWorld()
    world.site(HEALTH, HEALTH_IP, {
        "/robots.txt": ALLOW_ALL,
        "/scan.pdf": Reply(body=blank_pdf(30), content_type="application/pdf"),
    })  # fmt: skip
    with world.running():
        result = await collector(world).collect(f"http://{HEALTH}/scan.pdf", [])
    assert result.parse_outcome is ParseOutcome.UNREADABLE
    capped = DocumentParser(max_pages=3).parse_pdf(blank_pdf(30), [])
    assert capped.text.count("[page ") == 3


def test_a_window_normalised_once_matches_as_before() -> None:
    """RV-097: the normalised window is passed in instead of computed per draft."""
    window = "In Halden Bay, 31.5% of adults with hypertension had it controlled in 2024."
    params = QuoteParams(min_words=6, max_words=60, min_words_unique=3)
    quote = "31.5% of adults with hypertension had it controlled"
    assert match_quote(quote, window, params, "31.5%") == match_quote(
        quote, window, params, "31.5%", normalise(window)
    )


def test_wave0_runs_alongside_planning() -> None:
    """RV-098: both follow the city's resolution in the same step."""
    edges = {(e.source, e.target) for e in build_graph().get_graph().edges}
    assert ("resolve_city", "wave0") in edges
    assert ("resolve_city", "plan_slots") in edges
    assert ("wave0", "plan_slots") not in edges
