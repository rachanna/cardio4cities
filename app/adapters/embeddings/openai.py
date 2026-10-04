"""EmbeddingsPort over OpenAI embeddings (deployed and local-quality profiles)."""

from openai import APIError, AsyncOpenAI

from app.ports.errors import ProviderUnavailableError
from app.settings import Settings

BATCH = 128


class OpenAIEmbeddings:
    def __init__(
        self,
        api_key: str,
        model: str,
        dimension: int,
        key: str,
        base_url: str | None = None,
        max_retries: int = 2,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=max_retries)
        self._model, self._dimension, self._key = model, dimension, key

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def key(self) -> str:
        return self._key

    async def embed(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            try:
                response = await self._client.embeddings.create(
                    model=self._model, input=texts[start : start + BATCH]
                )
            except APIError as exc:
                raise ProviderUnavailableError(f"openai embeddings: {type(exc).__name__}") from exc
            vectors += [item.embedding for item in sorted(response.data, key=lambda d: d.index)]
        return vectors


def make(settings: Settings) -> OpenAIEmbeddings:
    config = settings.config
    provider = config.llm.providers["openai"]
    if not provider.api_key_env:
        raise ValueError("llm.providers.openai.api_key_env is required for OpenAI embeddings")
    e = config.embeddings
    return OpenAIEmbeddings(settings.secret(provider.api_key_env), e.model, e.dimension, e.key)
