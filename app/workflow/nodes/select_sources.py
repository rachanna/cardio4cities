"""select_sources (LLD-2 §14): de-duplicate across the run, deny list, publisher class,
rank by tier then search rank. The top N new URLs go to the crawl gate; URLs another slot
already fetched this run are reused, not fetched again (the run's fetch cache, BD-14), up
to their own cap."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.workflow.nodes._deps import deps
from app.workflow.rules.crawl_gate import canonicalise
from app.workflow.rules.selection import Candidate as Selected
from app.workflow.rules.selection import select_urls
from app.workflow.state import Candidate, SlotState


async def select_sources(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    raw = state.get("candidates", [])
    by_url: dict[str, Candidate] = {}
    for c in raw:
        key = canonicalise(c.url)
        if key and key not in by_url:
            by_url[key] = c
    if not d.fetch_cache.seeded:  # a resumed run: pages stored before the stop
        d.fetch_cache.seed(await d.relational.sources.fetched_sources(state["run_id"]))
    hits = [(c.url, c.rank) for c in raw]
    known = {u for u in by_url if d.fetch_cache.known(u)}
    everything = select_urls(hits, (), d.publishers, len(by_url))

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
