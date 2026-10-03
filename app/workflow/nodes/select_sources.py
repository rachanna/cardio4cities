"""select_sources (LLD-2 §14): de-duplicate across the run, deny list, publisher class,
rank by tier then search rank, keep the top N not already fetched."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.workflow.nodes._deps import deps
from app.workflow.rules.crawl_gate import canonicalise
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
    fetched = await d.relational.sources.fetched_urls(state["run_id"])
    chosen = select_urls([(c.url, c.rank) for c in raw], fetched, d.publishers, d.max_new_urls)
    selected = [
        Candidate(
            url=s.url,
            domain=s.domain,
            publisher_class=s.publisher_class.value,
            rank=s.search_rank,
            query_id=by_url[s.url].query_id,
        )
        for s in chosen
    ]
    return {"candidates": selected}
