"""select_sources (LLD-2 §14): de-duplicate across the run, deny list, publisher class,
rank by tier, then the other-place rule (BD-15), then search rank. The top N new URLs go
to the crawl gate; URLs another slot
already fetched this run are reused, not fetched again (the run's fetch cache, BD-14), up
to their own cap."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.workflow.deps import RunDeps
from app.workflow.nodes._deps import deps
from app.workflow.rules.crawl_gate import canonicalise
from app.workflow.rules.selection import Candidate as Selected
from app.workflow.rules.selection import select_urls
from app.workflow.state import Candidate, SlotState


async def seed_fetch_cache(d: RunDeps, run_id: str) -> None:
    """A resumed run knows the pages stored before the stop, whichever step a slot
    resumes at (BD-27; code review RV-029): only `select_sources` used to seed it, so a
    slot resumed at `fetch_parse` fetched a stored page again."""
    if not d.fetch_cache.seeded:
        d.fetch_cache.seed(await d.relational.sources.fetched_sources(run_id))


async def select_sources(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    raw = state.get("candidates", [])
    by_url: dict[str, Candidate] = {}
    for c in raw:
        key = canonicalise(c.url)
        if key and key not in by_url:
            by_url[key] = c
    await seed_fetch_cache(d, state["run_id"])
    hits = [(c.url, c.rank) for c in raw]
    known = {u for u in by_url if d.fetch_cache.known(u)}
    later = {u for u, c in by_url.items() if c.names_other_place}  # decided in search
    local = {u for u, c in by_url.items() if c.names_city} if d.prefer_local else set()
    everything = select_urls(hits, (), d.publishers, len(by_url), later, local)

    def candidate(s: Selected) -> Candidate:
        return Candidate(
            url=s.url,
            domain=s.domain,
            publisher_class=s.publisher_class.value,
            rank=s.search_rank,
            query_id=by_url[s.url].query_id,
        )

    new = [candidate(s) for s in everything if s.url not in known][: d.max_new_urls]
    reused = [candidate(s) for s in everything if s.url in known][: d.max_reused_urls]
    return {"candidates": new, "reused": reused}
