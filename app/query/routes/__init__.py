"""The four candidate routes (LLD-5 §4), each its own module behind one interface: an
async function returning a `RouteResult` of claim IDs, best first. They run in parallel;
nothing here decides what is in scope or verified: re-validation does (§5)."""

import time
from collections.abc import Awaitable, Callable

from app.query.types import RouteResult


async def timed(route: RouteResult, work: Callable[[RouteResult], Awaitable[None]]) -> RouteResult:
    started = time.monotonic()
    try:
        await work(route)
    except Exception as exc:  # one route failing never stops the others (LLD-5 §11)
        route.candidates, route.mentions = [], []
        route.status, route.note = "degraded", type(exc).__name__
    route.ms = int((time.monotonic() - started) * 1000)
    return route
