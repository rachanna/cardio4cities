"""The budget ledger (LLD-2 §12, R-50, R-61): every external call reserves first, and a
spent counter refuses further calls. Wind-down (D2-5): past 85 % of the wall clock no new
search or fetch starts, while model calls go on; each counter warns once; a resumed run
restores the counters it had used (BD-14). AT-19 is in tests/acceptance/test_breadth.py."""

import pytest

from app.workflow.budget import BudgetExhaustedError, BudgetLedger, BudgetLimits


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def ledger(clock: Clock | None = None, **limits: float) -> BudgetLedger:
    values: dict[str, float] = {"wall_clock_s": 300, "searches": 2, "fetches": 2, "tokens": 0,
                                "cost_micro_usd": 0, "wind_down_at": 0.85}  # fmt: skip
    values.update(limits)
    return BudgetLedger(BudgetLimits(**values), clock=clock or Clock())  # type: ignore[arg-type]


async def test_searches_and_fetches_stop_at_their_limits() -> None:
    led = ledger()
    for kind in ("search", "fetch"):
        await led.reserve(kind)
        await led.reserve(kind)
        with pytest.raises(BudgetExhaustedError):
            await led.reserve(kind)
    assert (led.searches, led.fetches) == (2, 2)


async def test_robots_requests_are_counted_not_limited() -> None:
    led = ledger(fetches=1)
    for _ in range(5):
        await led.reserve("robots")
    assert led.robots == 5


async def test_model_calls_stop_once_cost_is_spent_and_are_recorded_by_model() -> None:
    led = ledger(cost_micro_usd=1000)
    await led.reserve("model")
    await led.record_model("model-a", 100, 20, 600)
    await led.reserve("model")
    await led.record_model("model-a", 100, 20, 600)
    with pytest.raises(BudgetExhaustedError, match="cost"):
        await led.reserve("model")
    assert led.by_model["model-a"] == {
        "calls": 2, "tokens_in": 200, "tokens_out": 40, "cost_micro_usd": 1200,
        "cached_tokens": 0, "cache_write_tokens": 0, "reasoning_tokens": 0,  # BD-30
    }  # fmt: skip
    assert led.phase() == "exhausted"


async def test_wall_clock_refuses_every_kind_and_phases_follow_the_worst_counter() -> None:
    clock = Clock()
    led = ledger(clock)
    assert led.phase() == "normal"
    clock.now = 270  # 90% of 300 s
    assert led.phase() == "winding_down"
    clock.now = 300
    for kind in ("search", "fetch", "model"):
        with pytest.raises(BudgetExhaustedError, match="wall_clock"):
            await led.reserve(kind)
    assert led.snapshot()["wall_clock_ms"] == 300_000


async def test_winding_down_stops_new_searches_and_fetches_but_not_model_calls() -> None:
    clock = Clock()
    led = ledger(clock, searches=10, fetches=10)
    clock.now = 255  # 85% of 300 s
    for kind in ("search", "fetch", "robots"):
        with pytest.raises(BudgetExhaustedError, match="wall_clock"):
            await led.reserve(kind)
    await led.reserve("model")  # extraction and checking of what is in hand go on
    assert (led.searches, led.fetches, led.model_calls) == (0, 0, 1)
    assert led.refused == {"wall_clock"}


async def test_each_counter_warns_once_when_it_passes_the_wind_down_mark() -> None:
    warned: list[tuple[str, float, float]] = []

    async def hook(counter: str, used: float, limit: float) -> None:
        warned.append((counter, used, limit))

    led = ledger(searches=4)
    led.on_warning = hook
    for _ in range(3):
        await led.reserve("search")
    assert warned == []  # 3 of 4 is 75%
    await led.reserve("search")
    with pytest.raises(BudgetExhaustedError):
        await led.reserve("search")
    assert warned == [("searches", 4.0, 4.0)]
    assert led.snapshot()["refused"] == ["searches"]


async def test_a_resumed_run_carries_on_from_its_saved_counters() -> None:
    clock = Clock()
    first = ledger(clock, searches=10)
    await first.reserve("search")
    await first.reserve("model")
    await first.record_model("model-a", 100, 20, 500)
    clock.now = 120
    saved = first.snapshot()

    clock.now = 1000  # a new process: its own clock
    resumed = ledger(clock, searches=10)
    resumed.restore(saved)
    assert (resumed.searches, resumed.model_calls, resumed.cost_micro_usd) == (1, 1, 500)
    assert resumed.by_model == first.by_model
    assert resumed.snapshot()["wall_clock_ms"] == 120_000  # the clock carries on
