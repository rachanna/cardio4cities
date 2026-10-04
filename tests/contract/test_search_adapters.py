"""Search adapters against a local stand-in provider (AT-33). No paid calls. The shared
contract at the end runs every search adapter through the same tests (AT-35)."""

import http.server
import json
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest

from app.adapters.search.brave import BraveSearch
from app.adapters.search.searxng import SearxngSearch
from app.ports.errors import ProviderUnavailableError
from app.ports.search import SearchHit, SearchPort


class Provider:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.status = 200
        self.raw: bytes | None = None  # sent instead of the payload when set
        self.requests: list[tuple[str, dict[str, list[str]], dict[str, str]]] = []


@pytest.fixture
def provider() -> Iterator[tuple[Provider, str]]:
    state = Provider({})

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            parts = urlsplit(self.path)
            state.requests.append((parts.path, parse_qs(parts.query), dict(self.headers)))
            body = state.raw if state.raw is not None else json.dumps(state.payload).encode()
            self.send_response(state.status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield state, f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


RECORDED_BRAVE = Path(__file__).parents[1] / "fixtures" / "search" / "brave_web_search.json"
RESULTS = [
    {"url": "https://health.halden-bay.test/report", "title": "Annual report", "content": "short"},
    {"title": "no url, skipped"},
    {"url": "https://news.halden-bay.test/story", "title": "Story", "content": "snippet"},
]


async def test_searxng_returns_links_titles_snippets_and_ranks(
    provider: tuple[Provider, str],
) -> None:
    state, base = provider
    state.payload = {"results": RESULTS}

    hits = await SearxngSearch(base, rate_per_s=100, user_agent="test").search("heart", "en", 5)

    assert hits == [
        SearchHit(url=RESULTS[0]["url"], title="Annual report", snippet="short", rank=1),
        SearchHit(url=RESULTS[2]["url"], title="Story", snippet="snippet", rank=2),
    ]
    path, params, _ = state.requests[0]
    assert (path, params["format"], params["language"]) == ("/search", ["json"], ["en"])


async def test_brave_request_disables_content_retrieval(provider: tuple[Provider, str]) -> None:
    """AT-33: given the configured search adapter, when a search is made, the request
    disables content retrieval, and the hits carry links, titles and snippets only."""
    state, base = provider
    state.payload = {
        "web": {
            "results": [
                {
                    "url": RESULTS[0]["url"],
                    "title": "Annual report",
                    "description": "short",
                    "extra_snippets": ["page text"],
                }
            ]
        }
    }

    hits = await BraveSearch("test-key", 100, base_url=f"{base}/res/v1/web/search").search(
        "hypertension", "en", 5
    )

    _, params, headers = state.requests[0]
    assert params["extra_snippets"] == ["false"]
    assert params["summary"] == ["false"]
    assert params["result_filter"] == ["web"]
    assert headers.get("x-subscription-token") == "test-key"
    assert hits == [
        SearchHit(url=RESULTS[0]["url"], title="Annual report", snippet="short", rank=1)
    ]
    assert set(SearchHit.model_fields) == {"url", "title", "snippet", "rank"}  # no content field


async def test_brave_recorded_response_yields_links_titles_and_snippets_only(
    provider: tuple[Provider, str],
) -> None:
    """AT-33 against a recorded response (spike S-4, BD-14): Brave's real field layout,
    fictional values. Article metadata, profiles and thumbnails never reach a hit."""
    state, base = provider
    state.payload = json.loads(RECORDED_BRAVE.read_text(encoding="utf-8"))

    hits = await BraveSearch("test-key", 100, base_url=f"{base}/res/v1/web/search").search(
        "Halden Bay hypertension control survey", "en", 10
    )

    assert [h.url for h in hits] == [
        "https://health.halden-bay.test/heart-survey",
        "https://health.halden-bay.test/public-health",
    ]
    assert hits[0].title == "Halden Bay Heart Survey 2024"
    assert hits[0].snippet.startswith("Adults with hypertension")
    assert [h.rank for h in hits] == [1, 2]
    assert all(set(h.model_dump()) == {"url", "title", "snippet", "rank"} for h in hits)


# --- the shared SearchPort contract: every adapter, the same tests (AT-35, RV-102) ----------

ADAPTERS = ("searxng", "brave")


def adapter(name: str, base: str) -> SearchPort:
    if name == "searxng":
        return SearxngSearch(base, rate_per_s=100, user_agent="test")
    return BraveSearch("test-key", 100, base_url=f"{base}/res/v1/web/search")


def payload(name: str, results: list[dict[str, str]]) -> dict[str, Any]:
    """The provider's own layout for neutral results (url, title, snippet)."""
    if name == "searxng":
        return {"results": [{**r, "content": r.get("snippet", "")} for r in results]}
    return {"web": {"results": [{**r, "description": r.get("snippet", "")} for r in results]}}


NEUTRAL = [
    {"url": f"https://health.halden-bay.test/page-{n}", "title": f"Page {n}", "snippet": f"s{n}"}
    for n in range(1, 6)
]


@pytest.mark.parametrize("name", ADAPTERS)
async def test_every_adapter_returns_ranked_links_titles_and_snippets_only(
    provider: tuple[Provider, str], name: str
) -> None:
    state, base = provider
    state.payload = payload(name, [NEUTRAL[0], {"title": "no link"}, NEUTRAL[1]])

    hits = await adapter(name, base).search("Halden Bay heart health", "en", 10)

    assert hits == [
        SearchHit(url=NEUTRAL[0]["url"], title="Page 1", snippet="s1", rank=1),
        SearchHit(url=NEUTRAL[1]["url"], title="Page 2", snippet="s2", rank=2),
    ]


@pytest.mark.parametrize("name", ADAPTERS)
async def test_every_adapter_keeps_to_the_limit(provider: tuple[Provider, str], name: str) -> None:
    state, base = provider
    state.payload = payload(name, NEUTRAL)

    hits = await adapter(name, base).search("Halden Bay heart health", "en", 2)

    assert [h.rank for h in hits] == [1, 2]


@pytest.mark.parametrize("name", ADAPTERS)
async def test_every_adapter_gives_no_hits_for_no_results(
    provider: tuple[Provider, str], name: str
) -> None:
    state, base = provider
    state.payload = payload(name, [])

    assert await adapter(name, base).search("Halden Bay heart health", "en", 10) == []


@pytest.mark.parametrize("name", ADAPTERS)
@pytest.mark.parametrize(("status", "raw"), [(503, b"{}"), (200, b"not json")])
async def test_every_adapter_maps_a_provider_failure_to_the_port_error(
    provider: tuple[Provider, str], name: str, status: int, raw: bytes
) -> None:
    state, base = provider
    state.status, state.raw = status, raw

    with pytest.raises(ProviderUnavailableError, match=name):
        await adapter(name, base).search("Halden Bay heart health", "en", 10)
