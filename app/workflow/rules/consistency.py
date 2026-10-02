"""Consistency of newly supported claims (LLD-2 §5.4 statistics, §5.5 relations).

Different reference periods are a time series, not a conflict (WD-05). A conflict
never deletes anything: both claims become `contested` and a contested pair names
the headline claim, chosen by the ranking key (§5.2).
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from app.domain.dates import months_between
from app.domain.models import Claim, Labels, Relation, Statistic
from app.domain.params import ConsistencyParams
from app.domain.ranking import Candidate, rank_key
from app.domain.vocab import (
    SHOWABLE_STATUSES,
    SINGLE_CURRENT_RELATIONS,
    ConsistencyOutcome,
    GeographyLevel,
    PublisherClass,
)
from app.workflow.rules.comparability import comparability_key, differing_parts, key_gaps
from app.workflow.rules.numbers import PERCENT

PROXY_WINDOW_MONTHS = 12  # LLD-2 §5.5: proxy dates within 12 months cannot order two edges


@dataclass(frozen=True)
class StatisticFact:
    claim: Claim
    statistic: Statistic
    publisher_class: PublisherClass


@dataclass(frozen=True)
class RelationFact:
    claim: Claim
    relation: Relation
    publisher_class: PublisherClass


@dataclass(frozen=True)
class ContestedPair:
    claim_a: str  # claim_a < claim_b, as the table requires
    claim_b: str
    headline_claim: str
    reason: str


@dataclass(frozen=True)
class Decision:
    outcome: ConsistencyOutcome
    compared_with: tuple[str, ...]
    reason: str
    contested: tuple[ContestedPair, ...] = ()
    supersedes: tuple[str, ...] = ()  # relations: earlier claims this one end-dates
    new_is_history: bool = False  # relations: the new claim is older than the current edge


def _pair(
    a: Candidate, b: Candidate, accepted: Sequence[GeographyLevel], reason: str
) -> ContestedPair:
    first, second = sorted((a.claim.claim_id, b.claim.claim_id))
    headline = min((a, b), key=lambda c: rank_key(c, accepted)).claim.claim_id
    return ContestedPair(first, second, headline, reason)


# --- statistics (§5.4) ------------------------------------------------------------


def _period(labels: Labels) -> tuple[date, date] | None:
    start = labels.reference_start or labels.reference_end
    end = labels.reference_end or labels.reference_start
    return (start, end) if start and end else None


def _periods_overlap(a: Labels, b: Labels) -> bool:
    pa, pb = _period(a), _period(b)
    if pa is None or pb is None:
        return True  # an unknown period cannot make a time series
    return pa[0] <= pb[1] and pb[0] <= pa[1]


def _agree(a: Statistic, b: Statistic, params: ConsistencyParams) -> bool:
    if a.value_num is None or b.value_num is None:  # comparable keys guarantee values
        raise ValueError("only statistics with parsed values can be compared")
    diff = abs(a.value_num - b.value_num)
    if a.unit == PERCENT:
        return diff <= params.agree_pp
    largest = max(abs(a.value_num), abs(b.value_num))
    return largest == 0 or diff / largest <= params.agree_rel


def check_statistic(
    new: StatisticFact,
    others: Sequence[StatisticFact],
    accepted: Sequence[GeographyLevel],
    params: ConsistencyParams,
) -> Decision:
    """`others`: claims in the same run and city. Only supported or contested ones count."""
    live = [
        o
        for o in others
        if o.claim.status in SHOWABLE_STATUSES and o.claim.claim_id != new.claim.claim_id
    ]
    key = comparability_key(new.statistic, new.claim.labels)
    if key is None:
        same_indicator = [
            o for o in live if o.statistic.indicator_code == new.statistic.indicator_code
        ]
        return Decision(
            ConsistencyOutcome.NOT_COMPARABLE,
            tuple(o.claim.claim_id for o in same_indicator),
            "Not comparable: " + "; ".join(key_gaps(new.statistic, new.claim.labels)) + ".",
        )
    matches = [o for o in live if comparability_key(o.statistic, o.claim.labels) == key]
    if not matches:
        return Decision(ConsistencyOutcome.NOVEL, (), "No comparable figure yet.")

    agrees: list[StatisticFact] = []
    conflicts: list[StatisticFact] = []
    for o in matches:
        if not _periods_overlap(new.claim.labels, o.claim.labels):
            continue  # a time series, not a conflict (WD-05)
        (agrees if _agree(new.statistic, o.statistic, params) else conflicts).append(o)
    compared = tuple(o.claim.claim_id for o in matches)
    new_c = Candidate(new.claim, new.publisher_class)
    if conflicts:
        pairs = tuple(
            _pair(new_c, Candidate(o.claim, o.publisher_class), accepted, "values differ")
            for o in conflicts
        )
        return Decision(ConsistencyOutcome.CONFLICTS, compared, "Comparable figures differ.", pairs)
    if agrees:
        return Decision(ConsistencyOutcome.AGREES, compared, "Agrees with comparable figures.")
    return Decision(ConsistencyOutcome.NOVEL, compared, "Comparable figures cover other periods.")


def describe_difference(a: StatisticFact, b: StatisticFact) -> str:
    """For evidence panels: which key parts separate two figures."""
    parts = differing_parts((a.statistic, a.claim.labels), (b.statistic, b.claim.labels))
    return "Differ in " + ", ".join(parts) if parts else "Same comparability key"


# --- relations (§5.5) --------------------------------------------------------------


def _order(new: Relation, old: Relation) -> str:
    """'supersede', 'history' or 'conflict' for two edges into the same object (BD-06)."""
    if old.valid_to and new.valid_from and old.valid_to <= new.valid_from:
        return "supersede"  # the old edge ended before the new one started
    if new.valid_to and old.valid_from and new.valid_to <= old.valid_from:
        return "history"
    if new.valid_from is None or old.valid_from is None:
        return "conflict"  # cannot order: prefer "Sources disagree" to a silent replacement
    if (new.valid_from_is_proxy or old.valid_from_is_proxy) and months_between(
        new.valid_from, old.valid_from
    ) <= PROXY_WINDOW_MONTHS:
        return "conflict"
    if (old.valid_to and old.valid_to > new.valid_from) or (
        new.valid_to and new.valid_to > old.valid_from
    ):
        return "conflict"  # explicit validity overlap
    if new.valid_from.year > old.valid_from.year:
        return "supersede"
    if new.valid_from.year < old.valid_from.year:
        return "history"
    return "conflict"  # same year


def check_relation(
    new: RelationFact, current: Sequence[RelationFact], accepted: Sequence[GeographyLevel]
) -> Decision:
    """`current`: supported or contested relation claims in the same city.

    GOVERNS and LEADS allow one current edge per object (the place, or the
    organisation): same object and type, different subject, is a succession or a
    conflict. Other types: identical edge agrees, anything else is novel.
    """
    rel = new.relation
    live = [
        c
        for c in current
        if c.claim.status in SHOWABLE_STATUSES
        and c.claim.claim_id != new.claim.claim_id
        and c.relation.relation_type is rel.relation_type
    ]
    same_edge = [
        c
        for c in live
        if c.relation.subject_entity_id == rel.subject_entity_id
        and c.relation.object_entity_id == rel.object_entity_id
    ]
    if rel.relation_type not in SINGLE_CURRENT_RELATIONS:
        if same_edge:
            ids = tuple(c.claim.claim_id for c in same_edge)
            return Decision(ConsistencyOutcome.AGREES, ids, "Same relation already confirmed.")
        return Decision(ConsistencyOutcome.NOVEL, (), "New relation.")

    rivals = [
        c
        for c in live
        if c.relation.object_entity_id == rel.object_entity_id
        and c.relation.subject_entity_id != rel.subject_entity_id
    ]
    if not rivals:
        if same_edge:
            ids = tuple(c.claim.claim_id for c in same_edge)
            return Decision(ConsistencyOutcome.AGREES, ids, "Same relation already confirmed.")
        return Decision(ConsistencyOutcome.NOVEL, (), "No other current relation of this kind.")

    new_c = Candidate(new.claim, new.publisher_class)
    supersedes: list[str] = []
    conflicts: list[RelationFact] = []
    history = False
    for rival in rivals:
        verdict = _order(rel, rival.relation)
        if verdict == "supersede":
            supersedes.append(rival.claim.claim_id)
        elif verdict == "history":
            history = True
        else:
            conflicts.append(rival)
    compared = tuple(r.claim.claim_id for r in rivals)
    if conflicts:
        pairs = tuple(
            _pair(new_c, Candidate(r.claim, r.publisher_class), accepted, "overlapping validity")
            for r in conflicts
        )
        return Decision(
            ConsistencyOutcome.CONFLICTS,
            compared,
            "Another source names a different one for the same period.",
            pairs,
            tuple(supersedes),
        )
    if history:
        return Decision(
            ConsistencyOutcome.NOVEL,
            compared,
            "Older than the current relation; kept as history.",
            supersedes=tuple(supersedes),
            new_is_history=True,
        )
    return Decision(
        ConsistencyOutcome.NOVEL,
        compared,
        "Newer than the current relation, which it replaces.",
        supersedes=tuple(supersedes),
    )
