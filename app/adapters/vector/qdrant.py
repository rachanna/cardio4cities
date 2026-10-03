"""VectorPort over Qdrant (LLD-1 §5). Searches always filter by `city_id`, so one city's
chunks can never answer for another (contract test, AT-35)."""

from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.ports.vector import VectorHit, VectorPoint
from app.settings import Settings

# Source chunks and the claim index (LLD-5 §4.2) share one index set; unused fields cost nothing
KEYWORD_INDEXES = (
    "city_id",
    "run_id",
    "source_id",
    "slot_ids",
    "lang",
    "publisher_class",
    "claim_id",
    "slot_id",
    "kind",
    "status",
    "geography_level",
    "indicator_code",
)
DATETIME_INDEXES = ("published_date", "reference_end")


def _filter(filters: dict[str, Any]) -> models.Filter:
    conditions: list[models.Condition] = []
    for key, value in filters.items():
        match: models.MatchAny | models.MatchValue = (
            models.MatchAny(any=list(value))
            if isinstance(value, (list, tuple, set))
            else models.MatchValue(value=value)
        )
        conditions.append(models.FieldCondition(key=key, match=match))
    return models.Filter(must=conditions)


class QdrantVectorStore:
    def __init__(self, url: str, api_key: str | None) -> None:
        self._client = AsyncQdrantClient(
            url=url, api_key=api_key or None, timeout=10, check_compatibility=False
        )

    async def ensure_collection(self, name: str, dimension: int) -> None:
        if await self._client.collection_exists(name):
            return
        await self._client.create_collection(
            name,
            vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
        )
        for field in KEYWORD_INDEXES:
            await self._client.create_payload_index(name, field, models.PayloadSchemaType.KEYWORD)
        for field in DATETIME_INDEXES:
            await self._client.create_payload_index(name, field, models.PayloadSchemaType.DATETIME)

    async def collection_dimension(self, name: str) -> int | None:
        if not await self._client.collection_exists(name):
            return None
        info = await self._client.get_collection(name)
        vectors = info.config.params.vectors
        return vectors.size if isinstance(vectors, models.VectorParams) else None

    async def upsert(self, name: str, points: list[VectorPoint]) -> None:
        if not points:
            return
        await self._client.upsert(
            name,
            points=[
                models.PointStruct(id=p.id, vector=p.vector, payload=p.payload) for p in points
            ],
            wait=True,
        )

    async def search(
        self, name: str, vector: list[float], filters: dict[str, Any], limit: int
    ) -> list[VectorHit]:
        if "city_id" not in filters:
            raise ValueError("vector search must filter by city_id")
        result = await self._client.query_points(
            name, query=vector, query_filter=_filter(filters), limit=limit, with_payload=True
        )
        return [
            VectorHit(id=str(p.id), score=p.score, payload=p.payload or {}) for p in result.points
        ]

    async def delete_by_filter(self, name: str, filters: dict[str, Any]) -> None:
        if not filters:
            raise ValueError("refusing to delete without a filter")
        await self._client.delete(
            name, points_selector=models.FilterSelector(filter=_filter(filters)), wait=True
        )

    async def close(self) -> None:
        await self._client.close()


def make(settings: Settings) -> QdrantVectorStore:
    vector = settings.config.vector
    api_key = settings.secret(vector.api_key_env) if vector.api_key_env else None
    return QdrantVectorStore(settings.secret(vector.url_env), api_key)
