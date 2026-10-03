"""consistency (LLD-2 §5.4): comparability keys and conflicts among this slot's supported
statistics. Across slots and earlier claims of the run it widens in D2-5."""

from typing import Any

from langchain_core.runnables import RunnableConfig

from app.domain.vocab import ClaimKind, ClaimStatus, ConsistencyOutcome, EventType, PublisherClass
from app.workflow.ids import new_id
from app.workflow.nodes._deps import deps
from app.workflow.rules.comparability import comparability_key
from app.workflow.rules.consistency import StatisticFact, check_statistic
from app.workflow.state import SlotState


async def consistency(state: SlotState, config: RunnableConfig) -> dict[str, Any]:
    d = deps(config)
    slot = d.slots[state["slot_id"]]
    facts: list[StatisticFact] = []
    for claim_id in state.get("supported_claim_ids", []):
        claim, statistic = await d.relational.research.claim_with_statistic(claim_id)
        if claim.kind is not ClaimKind.STATISTIC or statistic is None:
            continue
        await d.relational.research.set_comparability_key(
            claim_id, comparability_key(statistic, claim.labels)
        )
        source = await d.relational.sources.source_for_extraction(claim.source_id) or {}
        new = StatisticFact(claim, statistic, PublisherClass(str(source.get("publisher_class"))))
        decision = check_statistic(new, facts, slot.accepted_levels, d.consistency)
        if decision.outcome is ConsistencyOutcome.CONFLICTS:
            for pair in decision.contested:
                pair_id = new_id("cp")
                await d.relational.research.add_contested_pair(
                    pair_id, pair.claim_a, pair.claim_b, pair.headline_claim, pair.reason
                )
                for member in (pair.claim_a, pair.claim_b):
                    await d.relational.research.set_claim_status(
                        member, ClaimStatus.CONTESTED.value
                    )
                await d.events.emit(
                    state["run_id"],
                    EventType.CONFLICT_FOUND,
                    {
                        "pair_id": pair_id,
                        "claim_a": pair.claim_a,
                        "claim_b": pair.claim_b,
                        "headline_claim": pair.headline_claim,
                    },
                )
        facts.append(new)
    return {}
