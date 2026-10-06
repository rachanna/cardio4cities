"""Model-call gates (BD-47): each provider has its own gate, so one role's queue on one
provider cannot hold up a role on another, and no provider sees more calls at once than
`llm.concurrency`."""

import asyncio

from pydantic import BaseModel

from app.ports.llm import LLMParams, LLMResult
from app.workflow.limits import limited_llms


class _Slow:
    """Records how many calls are in flight; each call waits until released."""

    def __init__(self, release: asyncio.Event) -> None:
        self.in_flight = self.peak = self.calls = 0
        self._release = release

    async def complete(
        self, role: str, system: str, user: str, schema: type[BaseModel], params: LLMParams
    ) -> LLMResult:
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        await self._release.wait()
        self.in_flight -= 1
        return None  # type: ignore[return-value]


async def test_a_provider_s_queue_does_not_hold_up_another_provider() -> None:
    release = asyncio.Event()
    first, second = _Slow(release), _Slow(release)
    llms = limited_llms({"first": first, "second": second}, concurrency=2)
    params = LLMParams(model="m", max_output_tokens=10)

    calls = [llms["first"].complete("extractor", "", "", BaseModel, params) for _ in range(5)]
    calls.append(llms["second"].complete("checker", "", "", BaseModel, params))
    tasks = [asyncio.create_task(c) for c in calls]
    await asyncio.sleep(0.01)

    assert (first.peak, second.calls) == (2, 1)  # the checker started while extraction queued
    release.set()
    await asyncio.gather(*tasks)
    assert (first.calls, first.peak) == (5, 2)
