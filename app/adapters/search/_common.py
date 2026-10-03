"""Shared pieces for search adapters: a per-adapter rate limit (search.rate_per_s)."""

import asyncio
import time


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
