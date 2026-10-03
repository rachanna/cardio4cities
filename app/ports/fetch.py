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

    async def fetch(
        self,
        url: str,
        pinned_ip: str,
        limits: FetchLimits,
        intermediates: tuple[bytes, ...] = (),
    ) -> FetchResult:
        """One request, dialled to `pinned_ip`; the hostname is kept for Host, SNI and
        certificate checks. `intermediates`: the result of `complete_chain`, used only to
        build the chain to a trusted root (BD-15, BD-16). Raises FetchError on network
        failure or timeout, TLSCertificateError when the certificate fails verification."""
        ...

    async def complete_chain(
        self, url: str, pinned_ip: str, limits: FetchLimits, issuers: tuple[bytes, ...]
    ) -> tuple[bytes, ...]:
        """Verify the server's chain with `issuers` (fetched from its AIA URLs) as untrusted
        intermediates, against the trusted roots and the host name; return the verified
        chain's intermediates. Raises TLSCertificateError when there is no such chain."""
        ...
