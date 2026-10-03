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

Kind = Literal["search", "fetch", "robots", "model"]
Phase = Literal["normal", "winding_down", "exhausted"]
WarningHook = Callable[[str, float, float], Awaitable[None]]  # counter, used, limit
WOUND_DOWN = frozenset({"search", "fetch", "robots"})  # refused once the clock winds down


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

    def phase(self) -> Phase:
        worst = max(self._ratios().values())
        if worst >= 1:
            return "exhausted"
        return "winding_down" if worst >= self.limits.wind_down_at else "normal"

    async def reserve(self, kind: Kind, est_tokens: int = 0) -> None:
        try:
            async with self._lock:
                self._reserve(kind)
        except BudgetExhaustedError as exc:
            self.refused.add(exc.counter)  # the run ends as stopped_by_budget
            raise
        finally:
            await self._warn()

    def _reserve(self, kind: Kind) -> None:
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

    async def record_model(self, model: str, tokens_in: int, tokens_out: int, cost: int) -> None:
        async with self._lock:
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
            self.cost_micro_usd += cost
            row = self.by_model.setdefault(
                model, {"calls": 0, "tokens_in": 0, "tokens_out": 0, "cost_micro_usd": 0}
            )
            row["calls"] += 1
            row["tokens_in"] += tokens_in
            row["tokens_out"] += tokens_out
            row["cost_micro_usd"] += cost
        await self._warn()

    def snapshot(self) -> dict[str, object]:
        return {
            "searches": self.searches,
            "fetches": self.fetches,
            "robots": self.robots,
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
