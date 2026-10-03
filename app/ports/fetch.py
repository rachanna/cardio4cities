"""Fetching (LLD-2 §9, LLD-4 §8; reshaped by BD-07).

The fetcher makes exactly one request to an address the crawl gate already
checked and never follows redirects: the collector re-gates every hop, so a
redirect can never reach an address the gate has not approved (AT-23).
"""

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class FetchLimits(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_bytes: int
    connect_timeout_s: float
    read_timeout_s: float
    user_agent: str


class FetchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    status: int
    headers: dict[str, str]  # lower-cased names
    content: bytes  # empty when the body was discarded or the size limit was hit
    content_type: str | None
    truncated: bool  # the body exceeded max_bytes; nothing was kept


class FetchPort(Protocol):
    async def resolve(self, host: str) -> list[str]:
        """Every address the host resolves to; empty when it does not resolve."""
        ...

    async def fetch(self, url: str, pinned_ip: str, limits: FetchLimits) -> FetchResult:
        """One request, dialled to `pinned_ip`; the hostname is kept for Host, SNI and
        certificate checks. Raises FetchError on network failure or timeout."""
        ...
