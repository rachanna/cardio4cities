"""Shared pieces for search adapters: a per-adapter rate limit (search.rate_per_s) and
the health probe."""

import asyncio
import time

from app.ports.search import SearchPort

# A neutral query that names no place; one link is asked for and none need come back
PROBE_QUERY = "cardiovascular health"


class RateLimit:
    def __init__(self, per_second: float) -> None:
        self._interval = 1.0 / per_second if per_second > 0 else 0.0
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            wait = self._last + self._interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last = time.monotonic()


class SearchProbe:
    """Health (LLD-4 §7, BD-42): one search for one link through the run's own adapter,
    so its rate limit applies. Links only, like every search (R-58)."""

    component = "search"

    def __init__(self, search: SearchPort) -> None:
        self._search = search

    async def check(self) -> None:
        await self._search.search(PROBE_QUERY, "en", limit=1)

    async def close(self) -> None:
        pass
