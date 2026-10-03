"""Slot status, flags and the re-plan rule (LLD-2 §11.1-11.3, R-79, AT-32).

Every slot always gets a status, including after a budget stop.
"""

from collections.abc import Iterable, Sequence

from app.domain.geography import effective_level
from app.domain.models import Claim, SlotDef
from app.domain.params import ReplanParams
from app.domain.vocab import (
    SHOWABLE_STATUSES,
    AnswerKind,
    Badge,
    CrawlOutcome,
    SlotFlag,
    SlotStatus,
)

RETRYABLE = frozenset({SlotStatus.ANSWERED_NEGATIVE, SlotStatus.BLOCKED, SlotStatus.UNREACHABLE})


def slot_status(
    slot: SlotDef,
    claims: Iterable[Claim],
    sources_fetched: int,
    crawl_outcomes: Sequence[CrawlOutcome],
) -> SlotStatus:
    """`claims`: every claim for the slot in this run; `crawl_outcomes`: its crawl decisions."""
    supported = [c for c in claims if c.status in SHOWABLE_STATUSES]
    if any(effective_level(c) in slot.accepted_levels for c in supported):
        return SlotStatus.ANSWERED
    if supported:
        return SlotStatus.ANSWERED_WIDER_GEO
    if sources_fetched == 0 and crawl_outcomes:
        if any(o.value.startswith("blocked") for o in crawl_outcomes):
            return SlotStatus.BLOCKED
        return SlotStatus.UNREACHABLE
    return SlotStatus.ANSWERED_NEGATIVE


def slot_flags(
    best_claim_id: str | None,
    contested_claim_ids: Iterable[str],
    best_main_badge: Badge | None,
    best_other_badges: Iterable[Badge] = (),
) -> frozenset[SlotFlag]:
    """`conflicting`: the best claim is in a contested pair; `stale`: it is outdated."""
    flags = set()
    if best_claim_id is not None and best_claim_id in set(contested_claim_ids):
        flags.add(SlotFlag.CONFLICTING)
    if Badge.OUTDATED in {best_main_badge, *best_other_badges}:
        flags.add(SlotFlag.STALE)
    return frozenset(flags)


def should_replan(
    slot: SlotDef,
    status: SlotStatus,
    replans_used: int,
    budget_warning: bool,
    params: ReplanParams,
) -> bool:
    """A slot is re-planned only while budget allows (§11.3)."""
    if budget_warning:
        return False
    if status in RETRYABLE:
        return replans_used < params.max_rounds
    if status is SlotStatus.ANSWERED_WIDER_GEO and slot.answer_kind is AnswerKind.STATISTIC:
        return replans_used < params.max_rounds_wider_geo
    return False
