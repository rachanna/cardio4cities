from typing import Protocol


class EmbeddingsPort(Protocol):
    @property
    def dimension(self) -> int: ...

    @property
    def key(self) -> str: ...

    async def embed(self, texts: list[str]) -> list[list[float]]: ...
