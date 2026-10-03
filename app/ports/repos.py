"""Relational repositories (LLD-4 §8, ID-04). Postgres is fixed (CON-04), so the
repositories are the port and SQL lives only in `app/adapters/postgres/`.

Each repository is added by the task that first needs it (BD-03).
"""

from typing import Protocol

from app.domain.models import CrawlDecision, Source


class ReferenceRepo(Protocol):
    async def slot_ids(self) -> list[str]: ...

    async def indicator_codes(self) -> dict[str, str]:
        """Registry indicator codes keyed 'provider.INDICATOR' (LLD-1 §3.4)."""
        ...


class SourceRepo(Protocol):
    """Crawl decisions and fetched sources of a run (LLD-1 §4.3)."""

    async def add_crawl_decision(self, decision: CrawlDecision) -> None: ...

    async def add_source(
        self, source: Source, parsed_text: str | None, crawl_decision_id: str | None
    ) -> None: ...

    async def fetched_urls(self, run_id: str) -> set[str]:
        """Canonical URLs already fetched in the run: the fetch cache (HD-01)."""
        ...


class RelationalPort(Protocol):
    @property
    def reference(self) -> ReferenceRepo: ...

    @property
    def sources(self) -> SourceRepo: ...

    async def ping(self) -> None:
        """`SELECT 1`; raises when the database is unreachable (LLD-4 §7)."""
        ...

    async def close(self) -> None: ...
