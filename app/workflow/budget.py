"""Budget guard (LLD-2 §12, R-50, R-61): every external call reserves first. Held in a
process-level ledger per run, not in graph state, so parallel slot branches cannot race
(WD-01).

Wind-down (§12, D2-5): once the wall clock passes `wind_down_at`, no new searches,
robots.txt requests or page fetches start; model calls go on until a limit is reached.
Re-plans stop when any counter passes `wind_down_at` (`phase() != "normal"`). The first
time a counter passes it, the `on_warning` hook is told (a `budget_warning` event).
On resume, `restore` puts back the counters saved with the run (BD-14)."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["search", "fetch", "robots", "certificate", "model", "embedding", "indexing"]
Phase = Literal["normal", "winding_down", "exhausted"]
WarningHook = Callable[[str, float, float], Awaitable[None]]  # counter, used, limit
WOUND_DOWN = frozenset({"search", "fetch", "robots", "certificate"})  # refused when winding down


MODEL_ROW = (
    "calls", "tokens_in", "tokens_out", "cost_micro_usd", "cached_tokens",
    "cache_write_tokens", "reasoning_tokens",
)  # fmt: skip


class BudgetExhaustedError(Exception):
    def __init__(self, counter: str) -> None:
        super().__init__(f"budget exhausted: {counter}")
        self.counter = counter


@dataclass(frozen=True)
class BudgetLimits:
    wall_clock_s: float  # budget.wall_clock_s
    searches: int  # budget.searches
    fetches: int  # budget.fetches
    tokens: int  # budget.tokens (0: not set, no limit)
    cost_micro_usd: int  # budget.cost_micro_usd (0: not set, no limit)
    wind_down_at: float  # budget.wind_down_at


@dataclass
class BudgetLedger:
    limits: BudgetLimits
    clock: Callable[[], float] = time.monotonic
    searches: int = 0
    fetches: int = 0
    robots: int = 0
    certificates: int = 0  # issuer certificates fetched from AIA URLs (BD-15)
    indexing: int = 0  # embedding calls for confirmed claims (BD-19)
    stopped: bool = False  # the run's task was cancelled (BD-27)
    model_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_micro_usd: int = 0
    by_model: dict[str, dict[str, int]] = field(default_factory=dict)
    started: float = field(default=0.0)
    on_warning: WarningHook | None = field(default=None, repr=False)
    warned: set[str] = field(default_factory=set)
    refused: set[str] = field(default_factory=set)  # counters that stopped a call
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self) -> None:
        self.started = self.clock()

    def _usage(self) -> dict[str, tuple[float, float]]:
        """Counter -> (used, limit), for the counters that have a limit."""
        lim = self.limits
        usage = {
            "wall_clock": (self.clock() - self.started, lim.wall_clock_s),
            "searches": (float(self.searches), float(lim.searches)),
            "fetches": (float(self.fetches), float(lim.fetches)),
        }
        if lim.tokens:
            usage["tokens"] = (float(self.tokens_in + self.tokens_out), float(lim.tokens))
        if lim.cost_micro_usd:
            usage["cost"] = (float(self.cost_micro_usd), float(lim.cost_micro_usd))
        return usage

    def _ratios(self) -> dict[str, float]:
        return {k: used / limit for k, (used, limit) in self._usage().items()}

    def time_left_s(self) -> float:
        """Seconds left on the run's wall clock: the cap on a model call (BD-15)."""
        return max(self.limits.wall_clock_s - (self.clock() - self.started), 0.0)

    def phase(self) -> Phase:
        worst = max(self._ratios().values())
        if worst >= 1:
            return "exhausted"
        return "winding_down" if worst >= self.limits.wind_down_at else "normal"

    def stop(self) -> None:
        """The run's task was cancelled (a shutdown or a crash): refuse every further
        external call, so work LangGraph left running does not go on (BD-27)."""
        self.stopped = True

    async def reserve(self, kind: Kind, est_tokens: int = 0) -> None:
        if self.stopped:  # not a budget refusal: the run is not finishing here
            raise BudgetExhaustedError("stopped")
        try:
            async with self._lock:
                self._reserve(kind)
        except BudgetExhaustedError as exc:
            self.refused.add(exc.counter)  # the run ends as stopped_by_budget
            raise
        finally:
            await self._warn()

    def _reserve(self, kind: Kind) -> None:
        if kind == "indexing":
            # Embeddings for claims already confirmed (claim index, graph edges): counted,
            # never refused, so a confirmed fact always reaches every store (BD-19)
            self.indexing += 1
            return
        ratios = self._ratios()
        if ratios["wall_clock"] >= 1:
            raise BudgetExhaustedError("wall_clock")
        if kind in WOUND_DOWN and ratios["wall_clock"] >= self.limits.wind_down_at:
            raise BudgetExhaustedError("wall_clock")  # winding down: finish what is in hand
        if kind == "search":
            if self.searches >= self.limits.searches:
                raise BudgetExhaustedError("searches")
            self.searches += 1
        elif kind == "fetch":
            if self.fetches >= self.limits.fetches:
                raise BudgetExhaustedError("fetches")
            self.fetches += 1
        elif kind == "robots":
            self.robots += 1  # counted, not limited: one per site per run
        elif kind == "certificate":
            self.certificates += 1  # counted, not limited: one per issuer URL per run
        elif kind == "embedding":  # counted by `record_embedding`, not as a model call
            if ratios.get("cost", 0) >= 1:
                raise BudgetExhaustedError("cost")
        else:
            for counter in ("tokens", "cost"):
                if ratios.get(counter, 0) >= 1:
                    raise BudgetExhaustedError(counter)
            self.model_calls += 1

    async def _warn(self) -> None:
        """Tell the hook, once per counter, that it passed `wind_down_at` (§10.2)."""
        crossed = [
            (counter, used, limit)
            for counter, (used, limit) in self._usage().items()
            if counter not in self.warned and used / limit >= self.limits.wind_down_at
        ]
        self.warned |= {counter for counter, _, _ in crossed}  # before any await: once only
        for counter, used, limit in crossed:
            if self.on_warning is not None:
                await self.on_warning(counter, used, limit)

    async def record_model(
        self,
        model: str,
        tokens_in: int,
        tokens_out: int,
        cost: int,
        cached_tokens: int = 0,
        reasoning_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        async with self._lock:
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
            self.cost_micro_usd += cost
            row = self.by_model.setdefault(model, dict.fromkeys(MODEL_ROW, 0))
            row["calls"] += 1
            row["tokens_in"] += tokens_in
            row["tokens_out"] += tokens_out
            row["cost_micro_usd"] += cost
            row["cached_tokens"] += cached_tokens  # BD-30
            row["cache_write_tokens"] += cache_write_tokens
            row["reasoning_tokens"] += reasoning_tokens
        await self._warn()

    async def record_embedding(self, model: str, tokens: int, cost: int) -> None:
        """Embeddings count apart from model calls (BD-30): their cost meets the cap,
        and they appear in the summary as `embeddings:<model>`."""
        async with self._lock:
            self.cost_micro_usd += cost
            row = self.by_model.setdefault(f"embeddings:{model}", dict.fromkeys(MODEL_ROW, 0))
            row["calls"] += 1
            row["tokens_in"] += tokens
            row["cost_micro_usd"] += cost
        await self._warn()

    def snapshot(self) -> dict[str, object]:
        return {
            "searches": self.searches,
            "fetches": self.fetches,
            "robots": self.robots,
            "certificates": self.certificates,
            "indexing": self.indexing,
            "model_calls": self.model_calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cost_micro_usd": self.cost_micro_usd,
            "wall_clock_ms": round((self.clock() - self.started) * 1000),
            "by_model": self.by_model,
            "phase": self.phase(),
            "refused": sorted(self.refused),
        }

    def restore(self, saved: dict[str, object]) -> None:
        """Counters saved with the run (`snapshot()`), on resume: the wall clock carries on
        from where the run stopped, so a resumed run cannot outlive its budget (BD-14)."""

        def count(key: str) -> int:
            value = saved.get(key, 0)
            return int(value) if isinstance(value, int | float | str) else 0

        self.searches, self.fetches, self.robots = (
            count("searches"),
            count("fetches"),
            count("robots"),
        )
        self.certificates = count("certificates")
        self.indexing = count("indexing")
        self.model_calls = count("model_calls")
        self.tokens_in, self.tokens_out = count("tokens_in"), count("tokens_out")
        self.cost_micro_usd = count("cost_micro_usd")
        refused = saved.get("refused")
        if isinstance(refused, list):
            self.refused = {str(r) for r in refused}
        by_model = saved.get("by_model")
        if isinstance(by_model, dict):
            self.by_model = {str(k): dict(v) for k, v in by_model.items()}
        self.started = self.clock() - count("wall_clock_ms") / 1000
