"""Conflicts among supported statistics, across the whole run (LLD-2 §5.4, BD-19).

Every coverage round compares each supported or contested statistic of the run with all
the others: every slot, every re-plan round and Wave 0 together. Running it once per
round, after every slot has finished, means parallel slots can never race past each
other. Each decision is stored in `consistency` (the latest round's), comparability keys
are set, and comparable figures that disagree become a contested pair, both shown.

Code only, no external call: it runs after a budget stop too.
"""

from app.domain.vocab import ClaimStatus, ConsistencyOutcome, EventType, PublisherClass
from app.workflow.claim_index import set_status
from app.workflow.deps import RunDeps
from app.workflow.graph_writes import mark_edge
from app.workflow.ids import stable_id
from app.workflow.rules.comparability import comparability_key
from app.workflow.rules.consistency import ContestedPair, StatisticFact, check_statistic

LIVE = [ClaimStatus.SUPPORTED.value, ClaimStatus.CONTESTED.value]


async def publisher(d: RunDeps, source_id: str) -> PublisherClass:
    source = await d.relational.sources.source_for_extraction(source_id) or {}
    return PublisherClass(str(source.get("publisher_class")))


async def contest(d: RunDeps, run_id: str, pairs: tuple[ContestedPair, ...]) -> None:
    """Both sides of a disagreement become contested, together (CLAUDE.md, R-65)."""
    for pair in pairs:
        pair_id = stable_id("cp", pair.claim_a, pair.claim_b)
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


async def sweep_statistics(d: RunDeps, run_id: str) -> int:
    """Compare every live statistic of the run with every other; returns the number of
    contested pairs found."""
    research = d.relational.research
    facts: list[StatisticFact] = []
    for claim_id in await research.statistic_claims(run_id, LIVE):
        claim, statistic = await research.claim_with_statistic(claim_id)
        if statistic is None:
            continue
        await research.set_comparability_key(claim_id, comparability_key(statistic, claim.labels))
        facts.append(StatisticFact(claim, statistic, await publisher(d, claim.source_id)))
    pairs: set[tuple[str, str]] = set()
    for fact in facts:
        claim_id = fact.claim.claim_id
        accepted = d.slots[fact.claim.slot_id].accepted_levels
        decision = check_statistic(fact, facts, accepted, d.consistency)
        await research.record_consistency(
            claim_id, decision.outcome.value, list(decision.compared_with), decision.reason
        )
        if decision.outcome is ConsistencyOutcome.CONFLICTS:
            fresh = tuple(p for p in decision.contested if (p.claim_a, p.claim_b) not in pairs)
            pairs |= {(p.claim_a, p.claim_b) for p in fresh}
            await contest(d, run_id, fresh)
    return len(pairs)
