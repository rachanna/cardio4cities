"""Qdrant health probe: lists collections (LLD-4 §7)."""

from qdrant_client import AsyncQdrantClient

from app.settings import Settings


class QdrantProbe:
    component = "qdrant"

    def __init__(self, url: str, api_key: str | None, timeout_s: int = 3) -> None:
        # No version check at construction: it is a blocking request the health check does not need.
        self._client = AsyncQdrantClient(
            url=url, api_key=api_key or None, timeout=timeout_s, check_compatibility=False
        )

    async def check(self) -> None:
        await self._client.get_collections()

    async def close(self) -> None:
        await self._client.close()


def make(settings: Settings) -> QdrantProbe:
    vector = settings.config.vector
    api_key = settings.secret(vector.api_key_env) if vector.api_key_env else None
    return QdrantProbe(settings.secret(vector.url_env), api_key)
