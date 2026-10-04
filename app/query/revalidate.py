"""Re-validation and scope (LLD-5 §5, binding): every candidate from every route is
checked against Postgres before anything else. Pure: the stored facts are read first."""

from collections import Counter
from collections.abc import Iterable, Mapping
from datetime import date

from app.domain.models import StoredFact
from app.domain.vocab import ClaimKind, ClaimStatus, VerdictLabel
from app.query.types import Understanding

SHOWN = frozenset({ClaimStatus.SUPPORTED, ClaimStatus.CONTESTED})


def _started(fact: StoredFact) -> date | None:
    if fact.relation is not None and fact.relation.valid_from is not None:
        return fact.relation.valid_from
    labels = fact.claim.labels
    return labels.reference_start or labels.reference_end


def _ended(fact: StoredFact) -> date | None:
    if fact.relation is None:
        return None
    return fact.relation.superseded_on or fact.relation.valid_to


def _true_at(fact: StoredFact, as_of: date) -> bool:
    """The claim's period, or the edge's validity, includes or precedes `as_of`; a
    relation ended by then no longer holds."""
    started = _started(fact)
    if started is not None and started > as_of:
        return False
    ended = _ended(fact)
    return not (fact.relation is not None and ended is not None and ended <= as_of)


def revalidate(
    candidates: Iterable[str],
    facts: Mapping[str, StoredFact],
    u: Understanding,
    city_id: str,
    run_id: str,
) -> tuple[list[str], Counter[str]]:
    """(kept claim IDs in candidate order, removals by reason). Kept only when all hold:
    the asked city, its latest run, a supported or contested status (superseded too for
    change questions or a date), a supported verdict, and, with a date, true at that date;
    then per slot only the latest statistic or statement at that date."""
    allow_superseded = u.question_type == "change_over_time" or u.as_of is not None
    kept: list[str] = []
    removed: Counter[str] = Counter()
    for claim_id in dict.fromkeys(candidates):
        fact = facts.get(claim_id)
        reason = None
        if fact is None:
            reason = "not_stored"
        elif fact.claim.city_id != city_id:
            reason = "other_city"
        elif fact.claim.run_id != run_id:
            reason = "other_run"
        elif fact.claim.status not in SHOWN and not (
            allow_superseded and fact.claim.status is ClaimStatus.SUPERSEDED
        ):
            reason = fact.claim.status.value
        elif fact.verdict is None or fact.verdict.label is not VerdictLabel.SUPPORTED:
            reason = "no_supported_verdict"
        elif u.as_of is not None and not _true_at(fact, u.as_of):
            reason = "out_of_time"
        if reason is None:
            kept.append(claim_id)
        else:
            removed[reason] += 1
    if u.as_of is not None:
        kept = _latest_per_slot(kept, facts, removed)
    return kept, removed


def _latest_per_slot(
    kept: list[str], facts: Mapping[str, StoredFact], removed: Counter[str]
) -> list[str]:
    """With a date, a statistic or statement slot keeps only its latest claim at that
    date (per indicator); relations keep every edge true at that date."""
    latest: dict[tuple[str, str], tuple[date, str]] = {}
    for claim_id in kept:
        fact = facts[claim_id]
        if fact.claim.kind is ClaimKind.RELATION:
            continue
        key = (fact.claim.slot_id, fact.indicator_code or "")
        when = fact.claim.labels.reference_end or _started(fact) or date.min
        if key not in latest or when > latest[key][0]:
            latest[key] = (when, claim_id)
    winners = {claim_id for _, claim_id in latest.values()}
    out = []
    for claim_id in kept:
        if facts[claim_id].claim.kind is ClaimKind.RELATION or claim_id in winners:
            out.append(claim_id)
        else:
            removed["not_latest_at_date"] += 1
    return out
