from typing import Protocol

from pydantic import BaseModel, ConfigDict


class SnapshotRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    sha256: str
    size_bytes: int
    content_type: str


class SnapshotPort(Protocol):
    async def put(self, source_id: str, content: bytes, content_type: str) -> SnapshotRef: ...

    async def get(self, source_id: str) -> tuple[bytes, str]: ...
