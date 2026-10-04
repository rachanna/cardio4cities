"""Bundle assembly (LLD-5 §7). Pure. Binding: a contested claim's partner comes right
after it; a slot's anchored best claim is always in."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.domain.models import StoredFact
from app.query.types import AskParams, Mention, Understanding


@dataclass
class Bundle:
    facts: list[str] = field(default_factory=list)  # claim IDs, in answer order
    mentions: list[Mention] = field(default_factory=list)
    partners: dict[str, str] = field(default_factory=dict)  # claim -> contested partner


def assemble(
    u: Understanding,
    fused: Sequence[tuple[str, float]],
    injected: Sequence[str],
    valid: set[str],
    facts: Mapping[str, StoredFact],
    pairs: Sequence[tuple[str, str]],
    mentions: Sequence[Mention],
    params: AskParams,
) -> Bundle:
    partner: dict[str, str] = {}
    for a, b in pairs:
        if a in valid and b in valid:
            partner[a], partner[b] = b, a
    order = {s: i for i, s in enumerate(u.slot_ids)}
    score = {c: s for c, s in fused}
    pool = list(dict.fromkeys([*injected, *(c for c, _ in fused)]))
    anchored = set(injected)

    def key(claim_id: str) -> tuple[int, int, float]:
        slot = facts[claim_id].claim.slot_id
        # asked slots first in the order asked; an anchored claim first within its slot
        return (
            order.get(slot, len(order)),
            0 if claim_id in anchored else 1,
            -score.get(claim_id, 0.0),
        )

    out = Bundle()
    per_slot: dict[str, int] = {}
    for claim_id in sorted(pool, key=key):
        if claim_id in out.facts:
            continue
        slot = facts[claim_id].claim.slot_id
        if per_slot.get(slot, 0) >= params.max_per_slot and claim_id not in anchored:
            continue
        group = [claim_id] + ([partner[claim_id]] if claim_id in partner else [])
        group = [c for c in group if c not in out.facts]
        if len(out.facts) + len(group) > params.max_facts and claim_id not in anchored:
            continue  # a pair is added whole or not at all
        out.facts += group
        per_slot[slot] = per_slot.get(slot, 0) + 1
    out.partners = {c: partner[c] for c in out.facts if c in partner}
    if u.question_type == "open" and len(out.facts) < params.mentions_only_if_facts_below:
        out.mentions = list(mentions)[: params.max_mentions]
    return out
