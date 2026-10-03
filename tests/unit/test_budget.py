"""The core budget ledger (LLD-2 §12, R-50): every external call reserves first, and a
spent counter refuses further calls. Wind-down rules and AT-19 come with D2-5."""

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
