"""One fetch per URL per run, shared by every slot (LLD-2 §14 step 1, BD-14).

The first slot to fetch a URL owns it; a slot that wants the same URL while it is in
flight waits for the owner, and a slot that wants it later reuses the stored source and
extracts it for its own question. The value is the source ID, or None when the page gave
no readable text (blocked, unreachable, unreadable): nothing to reuse.

A resumed run seeds the cache from the sources already stored for it."""

import asyncio
from collections.abc import Mapping


class FetchCache:
    def __init__(self) -> None:
        self._entries: dict[str, asyncio.Future[str | None]] = {}
        self.seeded = False

    def seed(self, stored: Mapping[str, str | None]) -> None:
        """Sources already stored for the run: URL -> source ID (None if not parsed)."""
        for url, source_id in stored.items():
            if url not in self._entries:
                self._entries[url] = self._done(source_id)
        self.seeded = True

    def known(self, url: str) -> bool:
        return url in self._entries

    def claim(self, url: str) -> asyncio.Future[str | None] | None:
        """None: the caller owns the URL and must `resolve` it. Otherwise the owner's
        future, to await."""
        if url in self._entries:
            return self._entries[url]
        self._entries[url] = asyncio.get_running_loop().create_future()
        return None

    def resolve(self, url: str, source_id: str | None) -> None:
        future = self._entries.get(url)
        if future is not None and not future.done():
            future.set_result(source_id)

    @staticmethod
    def _done(source_id: str | None) -> asyncio.Future[str | None]:
        future: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        future.set_result(source_id)
        return future
