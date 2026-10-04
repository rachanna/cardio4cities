"""Reciprocal rank fusion and slot anchors (LLD-5 §6). Pure."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain.models import SlotDef, StoredFact
from app.domain.ranking import Candidate, rank_key
from app.domain.vocab import SlotStatus

ANSWERED = frozenset({SlotStatus.ANSWERED.value, SlotStatus.ANSWERED_WIDER_GEO.value})


def fuse(
    routes: Mapping[str, Sequence[str]],
    kept: Sequence[str],
    facts: Mapping[str, StoredFact],
    slots: Mapping[str, SlotDef],
    k: int,
) -> list[tuple[str, float]]:
    """score = sum over routes of 1 / (k + rank); ties by the ranking key (LLD-2 §5.2),
    so trust decides between equally relevant claims. Only re-validated claims."""
    allowed = set(kept)
    scores: dict[str, float] = {}
    for ranked in routes.values():
        for rank, claim_id in enumerate(dict.fromkeys(ranked), start=1):
            if claim_id in allowed:
                scores[claim_id] = scores.get(claim_id, 0.0) + 1.0 / (k + rank)

    def key(claim_id: str) -> tuple[Any, ...]:
        fact = facts[claim_id]
        accepted = slots[fact.claim.slot_id].accepted_levels
        return (
            -scores[claim_id],
            rank_key(Candidate(fact.claim, fact.source.publisher_class), accepted),
        )

    return [(c, round(scores[c], 6)) for c in sorted(scores, key=key)]


@dataclass
class Anchors:
    injected: list[str] = field(default_factory=list)  # best claims no route found
    gaps: dict[str, dict[str, Any]] = field(default_factory=dict)  # slot -> slot_result row
    wider: dict[str, str] = field(default_factory=dict)  # slot -> gap note of a wider-area answer


def anchor(
    asked: Sequence[str],
    results: Mapping[str, Mapping[str, Any]],
    found: Sequence[str],
    valid: set[str],
) -> Anchors:
    """The recall guarantee (LLD-5 §6.2, binding): for each slot asked about, its first
    best claim is injected when no route found it (and it re-validates), or its gap
    record is attached. A wider-area answer carries its gap note too (§7 rule 3)."""
    out = Anchors()
    present = set(found)
    for slot_id in dict.fromkeys(asked):
        row = results.get(slot_id)
        if row is None:
            continue
        best = [c for c in row.get("best_claim_ids") or [] if c in valid]
        if row["status"] in ANSWERED and best:
            if best[0] not in present:
                out.injected.append(best[0])
                present.add(best[0])
            if row["status"] == SlotStatus.ANSWERED_WIDER_GEO.value and row.get("gap_note"):
                out.wider[slot_id] = str(row["gap_note"])
        else:
            out.gaps[slot_id] = dict(row)
    return out
