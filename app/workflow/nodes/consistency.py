"""consistency (LLD-2 §5.5): for this slot's newly supported relation claims, supersession,
history and conflicts against the run's other supported relation claims (BD-06 ordering,
LLD-1 §6.3). Statistics are compared across the whole run at each coverage round
(`workflow/conflicts.py`, BD-19), so every slot, round and Wave 0 figure meets the others.

Every status change goes through `claim_index.set_status`, so the retrieval indexes
follow (CHG-01). The date a superseded edge ends is stored on its relation row
(`superseded_on`, BD-19) before the status changes: an edge already in the graph is
end-dated here, and one not yet written is written already ended, by whichever slot
writes it.
"""

from collections.abc import Sequence
from datetime import date
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import ClaimKind, ClaimStatus, ConsistencyOutcome, GeographyLevel
from app.workflow.claim_index import set_status
from app.workflow.conflicts import contest, publisher
from app.workflow.deps import RunDeps
from app.workflow.graph_writes import end_edge
from app.workflow.nodes._deps import deps
from app.workflow.rules.consistency import RelationFact, check_relation
from app.workflow.state import SlotState


async def _relation_fact(d: RunDeps, claim_id: str) -> RelationFact | None:
    claim, _ = await d.relational.research.claim_with_statistic(claim_id)
    relation = await d.relational.research.relation(claim_id)
    if relation is None:
        return None
    return RelationFact(claim, relation, await publisher(d, claim.source_id))


async def consistency(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    run_id = state["run_id"]
    slot = d.slots[state["slot_id"]]
    for claim_id in state.get("supported_claim_ids", []):
        claim, _ = await d.relational.research.claim_with_statistic(claim_id)
        if claim.status not in (ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED):
            continue  # changed by an earlier decision in this loop
        if claim.kind is ClaimKind.RELATION:
            await _relations(d, run_id, claim_id, slot.accepted_levels)
    return {}


async def _supersede(d: RunDeps, claim_id: str, on: date) -> None:
    """The end date first, then the status: no reader ever sees a superseded claim
    without the date its edge ends (BD-19)."""
    await d.relational.research.set_superseded_on(claim_id, on)
    await set_status(d, claim_id, ClaimStatus.SUPERSEDED)
    await end_edge(d, claim_id, on)


async def _relations(
    d: RunDeps, run_id: str, claim_id: str, accepted: Sequence[GeographyLevel]
) -> None:
    new = await _relation_fact(d, claim_id)
    if new is None:
        return
    others = [
        fact
        for other in await d.relational.research.relation_claims(run_id, ["supported", "contested"])
        if other != claim_id and (fact := await _relation_fact(d, other)) is not None
    ]
    decision = check_relation(new, others, accepted)
    await d.relational.research.record_consistency(
        claim_id, decision.outcome.value, list(decision.compared_with), decision.reason
    )
    if decision.outcome is ConsistencyOutcome.CONFLICTS:
        await contest(d, run_id, decision.contested)
    start = new.relation.valid_from
    for old in decision.supersedes:  # the new edge replaces it from its start date
        await _supersede(d, old, start or date.today())
    if decision.new_is_history:  # older than the current edge: kept, ending where it starts
        later = [
            f.relation.valid_from
            for f in others
            if f.claim.claim_id in decision.compared_with
            and f.relation.valid_from
            and (start is None or f.relation.valid_from > start)
        ]
        await _supersede(d, claim_id, min(later) if later else (start or date.today()))
