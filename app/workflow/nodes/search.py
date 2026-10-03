"""search (LLD-2 §3.3): links only (R-58); each query reserves budget first."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import EventType
from app.ports.errors import PortError
from app.workflow.budget import BudgetExhaustedError
from app.workflow.ids import stable_id
from app.workflow.nodes._deps import deps
from app.workflow.state import Candidate, SlotState

RESULTS_PER_QUERY = 10


async def search(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    run_id, slot_id = state["run_id"], state["slot_id"]
    query_ids: list[str] = []
    candidates: list[Candidate] = []
    error = None
    for q in state["plan"].queries:
        try:
            await d.ledger.reserve("search")
            hits = await d.search.search(q.text, q.lang, RESULTS_PER_QUERY)
        except BudgetExhaustedError:
            break
        except PortError as exc:
            error = f"search: {exc}"
            hits = []
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
            Candidate(url=h.url, domain="", publisher_class="", rank=h.rank, query_id=query_id)
            for h in hits
        ]  # only the URL is used from here on: snippets never become evidence (AT-06)
    return {"query_ids": query_ids, "candidates": candidates, "error": error}
