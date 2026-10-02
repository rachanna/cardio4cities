from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class VectorPoint(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    vector: list[float]
    payload: dict[str, Any]


class VectorHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    score: float
    payload: dict[str, Any]


class VectorPort(Protocol):
    async def ensure_collection(self, name: str, dimension: int) -> None: ...

    async def collection_dimension(self, name: str) -> int | None:
        """Vector size of an existing collection, or None if absent (LLD-4 §5.2)."""
        ...

    async def upsert(self, name: str, points: list[VectorPoint]) -> None: ...

    async def search(
        self, name: str, vector: list[float], filters: dict[str, Any], limit: int
    ) -> list[VectorHit]: ...

    async def delete_by_filter(self, name: str, filters: dict[str, Any]) -> None: ...
