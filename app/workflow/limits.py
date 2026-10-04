"""Run-wide resource limits shared by every slot branch (LLD-2 §12, D2-5).

Slots run in parallel; what they share is limited here, not by how many slots run:
model calls (`llm.concurrency`) and embedding calls (`embeddings.concurrency`) through the
wrappers below; page fetches by the collector (`fetch.concurrency`, per-domain spacing);
searches by the search adapter's rate limit (`search.rate_per_s`).

`StageClock` adds up busy time per stage across branches, so parallel stages can add up
to more than the run's wall clock (the run summary shows both)."""

import asyncio
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable

from pydantic import BaseModel

from app.ports.embeddings import EmbeddingsPort
from app.ports.llm import LLMParams, LLMPort, LLMResult
from app.workflow.rules.chunking import estimate_tokens

# Graph node -> reported stage (AT-38). Nodes not listed are bookkeeping.
STAGE_OF = {
    "wave0": "wave0",
    "plan_slots": "planning",
    "search": "search",
    "select_sources": "fetch",
    "crawl_gate": "fetch",
    "fetch_parse": "fetch",
    "extract": "extraction",
    "match_quotes": "extraction",
    "verify": "verification",
    "consistency": "verification",
    "write": "writes",
    "coverage": "coverage",
}


class LimitedLLM:
    def __init__(self, inner: LLMPort, gate: asyncio.Semaphore) -> None:
        self._inner, self._gate = inner, gate

    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        async with self._gate:
            return await self._inner.complete(role, system, user, schema, params)


class LimitedEmbeddings:
    """The embeddings port under the global limit; each call's estimated tokens and cost
    are recorded on the ledger when one is given (BD-30)."""

    def __init__(
        self,
        inner: EmbeddingsPort,
        gate: asyncio.Semaphore,
        record: Callable[[int], Awaitable[None]] | None = None,
    ) -> None:
        self._inner, self._gate, self._record = inner, gate, record

    @property
    def dimension(self) -> int:
        return self._inner.dimension

    @property
    def key(self) -> str:
        return self._inner.key

    async def embed(self, texts: list[str]) -> list[list[float]]:
        async with self._gate:
            vectors = await self._inner.embed(texts)
        if self._record is not None:
            await self._record(sum(estimate_tokens(t) for t in texts))
        return vectors


class StageClock:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self.busy_s: dict[str, float] = defaultdict(float)

    def start(self) -> float:
        return self._clock()

    def stop(self, node: str, started: float) -> None:
        if (stage := STAGE_OF.get(node)) is not None:
            self.busy_s[stage] += self._clock() - started

    def snapshot(self) -> dict[str, int]:
        """Busy milliseconds per stage, in a fixed order."""
        order = list(dict.fromkeys(STAGE_OF.values()))
        return {stage: round(self.busy_s.get(stage, 0.0) * 1000) for stage in order}
