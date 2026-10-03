"""Stand-ins for the paid and heavy ports in offline workflow tests: scripted models (no
API calls), a links-only search, deterministic embeddings and an in-memory vector store.
Everything else in a test run is real: Postgres, the gate, pinned fetching, parsing."""

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from app.ports.embeddings import EmbeddingsPort
from app.ports.errors import ProviderUnavailableError
from app.ports.fetch import FetchPort
from app.ports.graph import GraphPort
from app.ports.llm import LLMParams, LLMPort, LLMResult
from app.ports.parse import ParserPort
from app.ports.repos import RelationalPort
from app.ports.robots import RobotsParser
from app.ports.search import SearchHit, SearchPort
from app.ports.snapshots import SnapshotPort
from app.ports.vector import VectorHit, VectorPoint, VectorPort

Handler = Callable[[str], BaseModel]  # user message -> parsed output


@dataclass
class Call:
    role: str
    model: str
    system: str
    user: str


@dataclass
class ScriptedLLM:
    """Answers each role with its handler; a role without one is unavailable."""

    family: str
    handlers: dict[str, Handler]
    calls: list[Call] = field(default_factory=list)

    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        self.calls.append(Call(role, params.model, system, user))
        if role not in self.handlers:
            raise ProviderUnavailableError(f"{self.family}: no script for {role}")
        parsed = self.handlers[role](user)
        if not isinstance(parsed, schema):
            raise TypeError(f"script for {role} returned {type(parsed).__name__}")
        return LLMResult(
            parsed=parsed, raw_text=parsed.model_dump_json(), model_id=params.model,
            family=self.family, tokens_in=1000, tokens_out=200, cost_micro_usd=100,
        )  # fmt: skip


@dataclass
class ListSearch:
    """Links only: the hits for a query from `by_query`, else `urls`."""

    urls: list[str]
    queries: list[str] = field(default_factory=list)
    by_query: dict[str, list[str]] = field(default_factory=dict)

    async def search(self, query: str, lang: str, limit: int = 10) -> list[SearchHit]:
        self.queries.append(query)
        urls = self.by_query.get(query, self.urls)
        return [
            SearchHit(url=u, title="Result", snippet="SNIPPET-TEXT-NEVER-EVIDENCE", rank=n)
            for n, u in enumerate(urls[:limit], 1)
        ]


class HashEmbeddings:
    """Deterministic stand-in for a real embedding model: 64 values in [-1, 1] from the
    text's SHA-512, so different texts score near 0 and identical texts 1, in every
    process. (An earlier all-positive 8-value version scored unrelated names above the
    entity merge threshold, by chance.)"""

    dimension = 64
    key = "test_hash_v2"

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [_unit_vector(t) for t in texts]


def _unit_vector(text: str) -> list[float]:
    digest = hashlib.sha512(text.encode("utf-8")).digest()
    return [(byte - 127.5) / 127.5 for byte in digest]


@dataclass
class MemoryVector:
    collections: dict[str, int] = field(default_factory=dict)
    points: dict[str, list[VectorPoint]] = field(default_factory=dict)

    async def ensure_collection(self, name: str, dimension: int) -> None:
        self.collections.setdefault(name, dimension)

    async def collection_dimension(self, name: str) -> int | None:
        return self.collections.get(name)

    async def upsert(self, name: str, points: list[VectorPoint]) -> None:
        ids = {p.id for p in points}  # same ID replaces, as in Qdrant
        kept = [p for p in self.points.get(name, []) if p.id not in ids]
        self.points[name] = kept + list(points)

    async def search(
        self, name: str, vector: list[float], filters: dict[str, Any], limit: int
    ) -> list[VectorHit]:
        return []

    async def delete_by_filter(self, name: str, filters: dict[str, Any]) -> None:
        def matches(point: VectorPoint) -> bool:
            return all(point.payload.get(k) == v for k, v in filters.items())

        self.points[name] = [p for p in self.points.get(name, []) if not matches(p)]


@dataclass
class Ports:
    """Satisfies `RunPorts` the way the container does."""

    relational: RelationalPort | None
    llm: dict[str, LLMPort]
    search: SearchPort | None
    fetch: FetchPort | None
    robots: RobotsParser | None
    parser: ParserPort | None
    embeddings: EmbeddingsPort | None
    vector: VectorPort | None
    snapshots: SnapshotPort | None
    graph: GraphPort | None
