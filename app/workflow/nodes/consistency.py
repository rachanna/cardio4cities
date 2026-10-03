"""consistency (LLD-2 §5.4-5.5): comparability keys and conflicts among this slot's
supported statistics; for relations, supersession, history and conflicts against the
run's other supported relation claims (BD-06 ordering, LLD-1 §6.3).

Every status change goes through `claim_index.set_status`, so the retrieval indexes
follow (CHG-01). Edges already in the graph are end-dated or marked contested here; edges
not yet written are written already ended by `write` (from `ended` in the slot state).
"""

from collections.abc import Sequence
from datetime import date
from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import (
    ClaimKind,
    ClaimStatus,
    ConsistencyOutcome,
    EventType,
    GeographyLevel,
    PublisherClass,
)
from app.workflow.claim_index import set_status
from app.workflow.deps import RunDeps
from app.workflow.graph_writes import end_edge, mark_edge
from app.workflow.ids import new_id
from app.workflow.nodes._deps import deps
from app.workflow.rules.comparability import comparability_key
from app.workflow.rules.consistency import (
    ContestedPair,
    RelationFact,
    StatisticFact,
    check_relation,
    check_statistic,
)
from app.workflow.state import SlotState


async def _publisher(d: RunDeps, source_id: str) -> PublisherClass:
    source = await d.relational.sources.source_for_extraction(source_id) or {}
    return PublisherClass(str(source.get("publisher_class")))


async def _relation_fact(d: RunDeps, claim_id: str) -> RelationFact | None:
    claim, _ = await d.relational.research.claim_with_statistic(claim_id)
    relation = await d.relational.research.relation(claim_id)
    if relation is None:
        return None
    return RelationFact(claim, relation, await _publisher(d, claim.source_id))


async def _contest(d: RunDeps, run_id: str, pairs: tuple[ContestedPair, ...]) -> None:
    for pair in pairs:
        pair_id = new_id("cp")
        await d.relational.research.add_contested_pair(
            pair_id, pair.claim_a, pair.claim_b, pair.headline_claim, pair.reason
        )
        for member in (pair.claim_a, pair.claim_b):
            await set_status(d, member, ClaimStatus.CONTESTED)
            await mark_edge(d, member, ClaimStatus.CONTESTED.value)
        await d.events.emit(
            run_id,
            EventType.CONFLICT_FOUND,
            {
                "pair_id": pair_id,
                "claim_a": pair.claim_a,
                "claim_b": pair.claim_b,
                "headline_claim": pair.headline_claim,
            },
        )


async def consistency(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    run_id = state["run_id"]
    slot = d.slots[state["slot_id"]]
    facts: list[StatisticFact] = []
    ended: dict[str, str] = {}  # claim ID -> ISO date its edge ends (written by `write`)
    for claim_id in state.get("supported_claim_ids", []):
        claim, statistic = await d.relational.research.claim_with_statistic(claim_id)
        if claim.status not in (ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED):
            continue  # changed by an earlier decision in this loop
        if claim.kind is ClaimKind.RELATION:
            await _relations(d, run_id, claim_id, slot.accepted_levels, ended)
            continue
        if claim.kind is not ClaimKind.STATISTIC or statistic is None:
            continue
        await d.relational.research.set_comparability_key(
            claim_id, comparability_key(statistic, claim.labels)
        )
        new = StatisticFact(claim, statistic, await _publisher(d, claim.source_id))
        decision = check_statistic(new, facts, slot.accepted_levels, d.consistency)
        if decision.outcome is ConsistencyOutcome.CONFLICTS:
            await _contest(d, run_id, decision.contested)
        facts.append(new)
    return {"ended": ended}


async def _relations(
    d: RunDeps,
    run_id: str,
    claim_id: str,
    accepted: Sequence[GeographyLevel],
    ended: dict[str, str],
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
    if decision.outcome is ConsistencyOutcome.CONFLICTS:
        await _contest(d, run_id, decision.contested)
    start = new.relation.valid_from
    for old in decision.supersedes:  # the new edge replaces it from its start date
        at = start or date.today()
        await set_status(d, old, ClaimStatus.SUPERSEDED)
        await end_edge(d, old, at)
        ended[old] = at.isoformat()
    if decision.new_is_history:  # older than the current edge: kept, ending where it starts
        later = [
            f.relation.valid_from
            for f in others
            if f.claim.claim_id in decision.compared_with
            and f.relation.valid_from
            and (start is None or f.relation.valid_from > start)
        ]
        await set_status(d, claim_id, ClaimStatus.SUPERSEDED)
        ended[claim_id] = min(later).isoformat() if later else (start or date.today()).isoformat()
