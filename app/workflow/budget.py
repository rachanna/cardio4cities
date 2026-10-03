"""Budget guard (LLD-2 §12, R-50, R-61): every external call reserves first. Held in a
process-level ledger per run, not in graph state, so parallel slot branches cannot race
(WD-01). D2-3 has the core; the wind-down rules that stop re-plans arrive with D2-5."""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

Kind = Literal["search", "fetch", "robots", "model"]
Phase = Literal["normal", "winding_down", "exhausted"]


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
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def __post_init__(self) -> None:
        self.started = self.clock()

    def _ratios(self) -> dict[str, float]:
        lim = self.limits
        ratios = {
            "wall_clock": (self.clock() - self.started) / lim.wall_clock_s,
            "searches": self.searches / lim.searches,
            "fetches": self.fetches / lim.fetches,
        }
        if lim.tokens:
            ratios["tokens"] = (self.tokens_in + self.tokens_out) / lim.tokens
        if lim.cost_micro_usd:
            ratios["cost"] = self.cost_micro_usd / lim.cost_micro_usd
        return ratios

    def phase(self) -> Phase:
        worst = max(self._ratios().values())
        if worst >= 1:
            return "exhausted"
        return "winding_down" if worst >= self.limits.wind_down_at else "normal"

    async def reserve(self, kind: Kind, est_tokens: int = 0) -> None:
        async with self._lock:
            ratios = self._ratios()
            if ratios["wall_clock"] >= 1:
                raise BudgetExhaustedError("wall_clock")
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
        }
