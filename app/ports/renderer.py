from typing import Protocol


class RendererPort(Protocol):
    async def to_pdf(self, html: str) -> bytes: ...
