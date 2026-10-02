"""EmbeddingsPort over Sentence Transformers (local profile, no cost). Optional install:
`uv sync --group local-embeddings`; never in the deployed image (BD-05)."""

import asyncio
from typing import Any

from app.settings import Settings


class SentenceTransformerEmbeddings:
    def __init__(self, model_name: str, dimension: int, key: str) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # optional dependency group
            raise RuntimeError(
                "sentence-transformers is not installed: run `uv sync --group local-embeddings`"
            ) from exc
        self._model: Any = SentenceTransformer(model_name, device="cpu")
        self._dimension, self._key = dimension, key

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def key(self) -> str:
        return self._key

    def reported_dimension(self) -> int:
        # renamed to get_embedding_dimension in sentence-transformers 5
        getter = getattr(self._model, "get_embedding_dimension", None)
        getter = getter or self._model.get_sentence_embedding_dimension
        return int(getter())

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = await asyncio.to_thread(
            self._model.encode, texts, normalize_embeddings=True, convert_to_numpy=True
        )
        return [list(map(float, v)) for v in vectors]


def make(settings: Settings) -> SentenceTransformerEmbeddings:
    e = settings.config.embeddings
    return SentenceTransformerEmbeddings(e.model, e.dimension, e.key)
