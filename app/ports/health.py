"""Health probes for stores (LLD-4 §7). One trivial round trip per store.

A probe raises on failure; the health router times it and maps the outcome to
`ok` or `down` without exposing the error, hostnames or URLs.
"""

from typing import Protocol


class HealthProbe(Protocol):
    @property
    def component(self) -> str:
        """Name in the health response, e.g. 'qdrant'."""
        ...

    async def check(self) -> None: ...

    async def close(self) -> None: ...
