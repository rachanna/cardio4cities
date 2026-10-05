"""SearchPort over the Brave Search API (deployed profile). Links only (R-58, AT-33):
every request explicitly turns off Brave's extra content (`extra_snippets`, `summary`)
and asks for web results only. Spike S-4 confirms the live behaviour."""

import httpx

from app.adapters.search._common import RateLimit, SearchProbe
from app.ports.errors import ProviderUnavailableError
from app.ports.search import SearchHit
from app.settings import Settings

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
LINKS_ONLY = {"extra_snippets": "false", "summary": "false", "result_filter": "web"}


class BraveSearch:
    def __init__(self, api_key: str, rate_per_s: float, base_url: str = BRAVE_URL) -> None:
        self._url = base_url
        self._limit = RateLimit(rate_per_s)
        self._headers = {"x-subscription-token": api_key, "accept": "application/json"}

    async def search(self, query: str, lang: str, limit: int = 10) -> list[SearchHit]:
        await self._limit.wait()
        params = {"q": query, "count": str(min(limit, 20)), "search_lang": lang, **LINKS_ONLY}
        try:
            async with httpx.AsyncClient(timeout=20, headers=self._headers) as client:
                response = await client.get(self._url, params=params)
                response.raise_for_status()
                results = response.json().get("web", {}).get("results", [])
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderUnavailableError(f"brave: {type(exc).__name__}") from exc
        hits = [r for r in results if r.get("url")][:limit]
        return [
            SearchHit(
                url=str(r["url"]),
                title=str(r.get("title") or ""),
                snippet=str(r.get("description") or ""),
                rank=n,
            )
            for n, r in enumerate(hits, start=1)
        ]


def make(settings: Settings) -> BraveSearch:
    search = settings.config.search
    if not search.api_key_env:
        raise ValueError("search.api_key_env is required for brave")
    return BraveSearch(settings.secret(search.api_key_env), search.rate_per_s)


def make_probe(settings: Settings, search: BraveSearch) -> SearchProbe:
    return SearchProbe(search)
