"""Reviewer H scratch: collector behaviour under concurrent slots (fictional Halden Bay web)."""

import asyncio
from itertools import pairwise

from tests.support.webworld import ALLOW_ALL, Reply, WebWorld, article, collector

HOST, IP = "health.halden-bay.test", "93.184.216.34"


async def test_robots_once_per_origin_when_slots_ask_at_once() -> None:
    world = WebWorld()
    world.site(
        HOST, IP, {"/robots.txt": ALLOW_ALL, **{f"/p{n}": Reply(body=article()) for n in range(4)}}
    )
    with world.running():
        c = collector(world)
        await asyncio.gather(*(c.collect(f"http://{HOST}/p{n}", []) for n in range(4)))
    assert world.paths(HOST).count("/robots.txt") == 1


async def test_crawl_delay_holds_for_concurrent_requests() -> None:
    world = WebWorld()
    robots = Reply(200, b"User-agent: *\nCrawl-delay: 1\nAllow: /\n", "text/plain")
    world.site(
        HOST, IP, {"/robots.txt": robots, **{f"/p{n}": Reply(body=article()) for n in range(3)}}
    )
    with world.running():
        c = collector(world)
        await asyncio.gather(*(c.collect(f"http://{HOST}/p{n}", []) for n in range(3)))
    times = sorted(h.at for h in world.log if h.path.startswith("/p"))
    assert len(times) == 3
    assert all(b - a >= 0.95 for a, b in pairwise(times)), times
