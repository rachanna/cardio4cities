"""SearchPort over a SearXNG instance (local profile). Links only (R-58, AT-33): SearXNG
returns result links with short snippets and has no page-content feature to enable."""

import httpx

from app.adapters.search._common import RateLimit, SearchProbe
from app.ports.errors import ProviderUnavailableError
from app.ports.search import SearchHit
from app.settings import Settings


class SearxngSearch:
    def __init__(self, base_url: str, rate_per_s: float, user_agent: str) -> None:
        self._base = base_url.rstrip("/")
        self._limit = RateLimit(rate_per_s)
        self._headers = {"user-agent": user_agent, "accept": "application/json"}

    async def search(self, query: str, lang: str, limit: int = 10) -> list[SearchHit]:
        await self._limit.wait()
        params = {"q": query, "format": "json", "language": lang, "safesearch": "0", "pageno": "1"}
        try:
            async with httpx.AsyncClient(timeout=20, headers=self._headers) as client:
                response = await client.get(f"{self._base}/search", params=params)
                response.raise_for_status()
                results = response.json().get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailableError(f"searxng: {type(exc).__name__}") from exc
        return [
            SearchHit(
                url=str(r["url"]),
                title=str(r.get("title") or ""),
                snippet=str(r.get("content") or ""),
                rank=n,
            )
            for n, r in enumerate((r for r in results if r.get("url")), start=1)
            if n <= limit
        ]


def make(settings: Settings) -> SearxngSearch:
    search = settings.config.search
    if not search.base_url:
        raise ValueError("search.base_url is required for searxng")
    return SearxngSearch(search.base_url, search.rate_per_s, settings.config.app.user_agent)


def make_probe(settings: Settings, search: SearxngSearch) -> SearchProbe:
    return SearchProbe(search)
