"""SnapshotPort over Postgres (LLD-1 §4.3): raw bytes, gzip-compressed, with their sha256.
Structured API sources keep the exact response body, so code verification can re-read it."""

import gzip
import hashlib

from sqlalchemy import text

from app.adapters.postgres.db import create_engine
from app.ports.snapshots import SnapshotRef
from app.settings import Settings


class SnapshotTooLargeError(ValueError):
    pass


class PostgresSnapshots:
    def __init__(self, database_url: str, max_bytes: int) -> None:
        self._engine = create_engine(database_url)
        self._max_bytes = max_bytes

    async def put(self, source_id: str, content: bytes, content_type: str) -> SnapshotRef:
        if len(content) > self._max_bytes:
            raise SnapshotTooLargeError(f"{len(content)} bytes is over the snapshot limit")
        ref = SnapshotRef(
            source_id=source_id,
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            content_type=content_type,
        )
        async with self._engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO snapshot (source_id, content_gz, content_type, sha256, size_bytes)"
                    " VALUES (:source_id, :content_gz, :content_type, :sha256, :size_bytes)"
                    " ON CONFLICT (source_id) DO NOTHING"
                ),
                ref.model_dump() | {"content_gz": gzip.compress(content, mtime=0)},
            )
        return ref

    async def get(self, source_id: str) -> tuple[bytes, str]:
        async with self._engine.connect() as conn:
            row = (
                await conn.execute(
                    text(
                        "SELECT content_gz, content_type, sha256 FROM snapshot"
                        " WHERE source_id = :source_id"
                    ),
                    {"source_id": source_id},
                )
            ).one()
        content = gzip.decompress(row.content_gz)
        if hashlib.sha256(content).hexdigest() != row.sha256:
            raise ValueError(f"snapshot {source_id} does not match its sha256")
        return content, row.content_type or "application/octet-stream"

    async def close(self) -> None:
        await self._engine.dispose()


def make(settings: Settings) -> PostgresSnapshots:
    config = settings.config
    return PostgresSnapshots(settings.secret(config.relational.dsn_env), config.snapshots.max_bytes)
