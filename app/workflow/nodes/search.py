"""search (LLD-2 §3.3): links only (R-58); each query reserves budget first."""

import asyncio
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import EventType
from app.ports.errors import PortError
from app.ports.search import SearchHit
from app.workflow.budget import BudgetExhaustedError
from app.workflow.collection import NETWORK_RETRY_DELAY_S
from app.workflow.deps import RunDeps
from app.workflow.ids import stable_id
from app.workflow.nodes._deps import deps
from app.workflow.problems import step_failed
from app.workflow.state import Candidate, SlotState

RESULTS_PER_QUERY = 10


async def _search(d: RunDeps, text: str, lang: str) -> list[SearchHit]:
    """One retry after 1 s (LLD-2 §17); each attempt is reserved first."""
    await d.ledger.reserve("search")
    try:
        return await d.search.search(text, lang, RESULTS_PER_QUERY)
    except PortError:
        await asyncio.sleep(NETWORK_RETRY_DELAY_S)
    await d.ledger.reserve("search")
    return await d.search.search(text, lang, RESULTS_PER_QUERY)


async def search(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    run_id, slot_id = state["run_id"], state["slot_id"]
    query_ids: list[str] = []
    candidates: list[Candidate] = []
    error = None
    for q in state["plan"].queries:
        try:
            hits = await _search(d, q.text, q.lang)
        except BudgetExhaustedError:
            break
        except PortError as exc:
            # Not stored as a query tried: a re-plan may try it again (BD-21)
            error = f"search: {exc}"
            await step_failed(d, state, "search", q.text, exc)
            continue
        query_id = stable_id("sq", run_id, slot_id, str(state.get("round", 0)), q.lang, q.text)
        await d.relational.research.add_search(
            query_id,
            run_id,
            slot_id,
            q.text,
            q.lang,
            d.search_provider,
            len(hits),
            state.get("round", 0),
        )
        await d.events.emit(
            run_id,
            EventType.SEARCH_DONE,
            {"slot_id": slot_id, "query_id": query_id, "result_count": len(hits)},
        )
        query_ids.append(query_id)
        candidates += [
            Candidate(
                url=h.url,
                domain="",
                publisher_class="",
                rank=h.rank,
                query_id=query_id,
                title=h.title,
                snippet=h.snippet,
            )
            for h in hits
        ]  # title and snippet only rank candidates: they never become evidence (AT-06)
    return {"query_ids": query_ids, "candidates": candidates, "error": error}
