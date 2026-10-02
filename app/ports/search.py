from typing import Protocol

from pydantic import BaseModel, ConfigDict


class SearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    url: str
    title: str
    snippet: str
    rank: int


class SearchPort(Protocol):
    async def search(self, query: str, lang: str, limit: int = 10) -> list[SearchHit]:
        """Links only. Adapters MUST disable provider content retrieval (AT-33)."""
        ...
