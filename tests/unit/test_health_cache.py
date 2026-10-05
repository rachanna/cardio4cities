"""The provider check cache behind /health (LLD-4 §7, BD-42). Pure: a fake clock."""

import asyncio

from app.api.routers.health import CachedCheck
from app.api.schemas import ComponentHealth


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def test_a_result_is_reused_until_the_period_has_passed() -> None:
    clock, calls = Clock(), []

    async def check() -> ComponentHealth:
        calls.append(clock.now)
        return ComponentHealth(status="ok" if len(calls) == 1 else "down")

    cached = CachedCheck(check, ttl_s=600, clock=clock)

    async def scenario() -> list[str]:
        seen: list[str] = [(await cached()).status]
        clock.now = 599
        seen.append((await cached()).status)
        clock.now = 600
        seen.append((await cached()).status)
        return seen

    assert asyncio.run(scenario()) == ["ok", "ok", "down"]
    assert calls == [0, 600]


def test_concurrent_callers_share_one_check() -> None:
    calls = []

    async def check() -> ComponentHealth:
        calls.append(1)
        await asyncio.sleep(0.01)
        return ComponentHealth(status="ok")

    cached = CachedCheck(check, ttl_s=600, clock=Clock())

    async def scenario() -> None:
        await asyncio.gather(*(cached() for _ in range(5)))

    asyncio.run(scenario())
    assert calls == [1]
