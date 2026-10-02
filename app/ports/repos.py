"""Relational repositories (LLD-4 §8, ID-04). Postgres is fixed (CON-04), so the
repositories are the port and SQL lives only in `app/adapters/postgres/`.

Each repository is added by the task that first needs it (BD-03).
"""

from typing import Protocol


class ReferenceRepo(Protocol):
    async def slot_ids(self) -> list[str]: ...

    async def indicator_codes(self) -> dict[str, str]:
        """Registry indicator codes keyed 'provider.INDICATOR' (LLD-1 §3.4)."""
        ...


class RelationalPort(Protocol):
    @property
    def reference(self) -> ReferenceRepo: ...

    async def ping(self) -> None:
        """`SELECT 1`; raises when the database is unreachable (LLD-4 §7)."""
        ...

    async def close(self) -> None: ...
