"""FactCards and SlotRows (LLD-4 §2.1): what the brief, findings, answers and report show
of a fact or a slot, with the user-facing words beside the internal values (R-90). Pure:
badges and confidence are computed here at read time (LLD-2 §7-8) from stored facts."""

import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel

from app.domain.badges import badges
from app.domain.confidence import confidence
from app.domain.geography import effective_level
from app.domain.models import SlotDef, StoredFact
from app.domain.params import BadgeParams, ConfidenceParams
from app.domain.vocab import (
    SHOWABLE_STATUSES,
    Badge,
    ClaimFlag,
    ConfidenceLabel,
    DatePrecision,
    GeographyLevel,
    PeriodType,
    RelationType,
    SlotStatus,
)
from app.domain.wording import (
    BADGE_LABELS,
    CLAIM_STATUS_WORDS,
    CONFIDENCE_WORDS,
    LEVEL_WORDS,
    SLOT_STATUS_WORDS,
)

SUMMARY_PER_DIMENSION = 3  # LLD-4 §3.3: up to 3 facts per dimension in the brief


@dataclass(frozen=True)
class SummaryTopics:
    """What may enter the summary (D4-3; `reference/summary_topics.yaml`): a fact whose
    statement names a topic of the brief, or any fact of a dimension about who governs
    or works on it. A true but off-topic fact stays under its question."""

    stems: tuple[str, ...]
    any_topic_dimensions: frozenset[str]

    def admits(self, card: "FactCard", dimension: str) -> bool:
        if dimension in self.any_topic_dimensions:
            return True
        text = card.statement.casefold()
        return any(re.search(rf"\b{re.escape(stem)}", text) for stem in self.stems)


def hide_global(cards: Sequence["FactCard"], keep: Iterable[str] = ()) -> list["FactCard"]:
    """Per question, world-level facts are left out when the question has any narrower
    fact: a world figure says nothing a national or city one does not (owner, D4-3).
    They stay stored, and a question can still reach them. `keep`: claims that are one
    side of a disagreement, always shown with the other side."""
    world = GeographyLevel.GLOBAL.value
    keep = set(keep)
    narrower = {c.slot_id for c in cards if c.geography.level != world}
    return [
        c
        for c in cards
        if c.geography.level != world or c.slot_id not in narrower or c.claim_id in keep
    ]


def fold_repeats(cards: Sequence["FactCard"]) -> list[tuple["FactCard", list["FactCard"]]]:
    """Each card once, in order, with the later cards of its question that repeat it: the
    same statement and value, as when one document is found at two addresses (D4-3).
    Different values never fold, so both sides of a disagreement stay."""
    kept: dict[tuple[str, str, str], tuple[FactCard, list[FactCard]]] = {}
    for card in cards:
        key = (
            card.slot_id,
            " ".join(card.statement.casefold().split()),
            card.value_as_written or "",
        )
        if key in kept:
            kept[key][1].append(card)
        else:
            kept[key] = (card, [])
    return list(kept.values())


class GeographyCard(BaseModel):
    level: str
    level_word: str
    name: str


class PeriodCard(BaseModel):
    start: str | None
    end: str | None
    type: str
    stated: bool  # False: the source gives no period; the publication date stands in


class PopulationCard(BaseModel):
    """Who the figure is about (AT-14; BD-37): a sub-population shows here, flagged."""

    age_min: int | None
    age_max: int | None
    sex: str
    group: str | None
    subgroup: bool


class BadgeCard(BaseModel):
    code: str
    label: str


class ReasonCard(BaseModel):
    component: str
    points: int
    note: str


class ConfidenceCard(BaseModel):
    label: str
    label_word: str
    points: int
    reasons: list[ReasonCard]
    capped_by: str | None = None


class SourceCard(BaseModel):
    source_id: str
    publisher_class: str
    title: str | None
    url: str
    published_date: date | None
    retrieved_at: str


class FactCard(BaseModel):
    claim_id: str
    slot_id: str
    kind: str
    statement: str
    value_as_written: str | None
    geography: GeographyCard
    period: PeriodCard
    population: PopulationCard
    status: str
    status_word: str
    main_badge: BadgeCard | None
    other_badges: list[BadgeCard]
    confidence: ConfidenceCard | None  # only for supported or contested claims
    source: SourceCard


class SlotRow(BaseModel):
    slot_id: str
    dimension: str
    question: str
    headline: bool
    status: str
    status_word: str
    flags: list[str]
    gap_note: str | None
    best_claim_ids: list[str]
    queries: int
    sources: int
    replans_used: int


class CareItem(BaseModel):
    """A fact to read with care, and why (LLD-2 §16.6)."""

    card: FactCard
    reason: str


def _day(value: date | None, precision: DatePrecision | None) -> str | None:
    if value is None:
        return None
    if precision is DatePrecision.YEAR:
        return f"{value.year:04d}"
    if precision is DatePrecision.MONTH:
        return f"{value.year:04d}-{value.month:02d}"
    return value.isoformat()


def _badge(badge: Badge) -> BadgeCard:
    return BadgeCard(code=badge.value, label=BADGE_LABELS[badge])


def fact_card(
    fact: StoredFact,
    slot: SlotDef,
    today: date,
    badge_params: BadgeParams,
    confidence_params: ConfidenceParams,
) -> FactCard:
    claim, labels = fact.claim, fact.claim.labels
    relation_type = fact.relation.relation_type if fact.relation else None
    found = badges(claim, slot.accepted_levels, today, badge_params, relation_type)
    level = effective_level(claim)
    shown = None
    if claim.status in SHOWABLE_STATUSES:
        c = confidence(
            claim, fact.source.publisher_class, slot.accepted_levels, fact.verdict, today,
            confidence_params,
        )  # fmt: skip
        shown = ConfidenceCard(
            label=c.label.value,
            label_word=CONFIDENCE_WORDS[c.label],
            points=c.points,
            reasons=[
                ReasonCard(component=r.component, points=r.points, note=r.note) for r in c.reasons
            ],
            capped_by=c.capped_by,
        )
    stated = (
        ClaimFlag.PERIOD_NOT_STATED not in claim.flags
        and labels.period_type is not PeriodType.PUBLICATION_DATE_PROXY
    )
    return FactCard(
        claim_id=claim.claim_id,
        slot_id=claim.slot_id,
        kind=claim.kind.value,
        statement=claim.statement,
        value_as_written=fact.value_as_written,
        geography=GeographyCard(
            level=level.value, level_word=LEVEL_WORDS[level], name=labels.geography_name
        ),
        period=PeriodCard(
            start=_day(labels.reference_start, labels.reference_precision),
            end=_day(labels.reference_end, labels.reference_precision),
            type=labels.period_type.value,
            stated=stated,
        ),
        population=PopulationCard(
            age_min=labels.population_age_min,
            age_max=labels.population_age_max,
            sex=labels.population_sex.value,
            group=labels.population_group,
            subgroup=bool(labels.population_subgroup),
        ),
        status=claim.status.value,
        status_word=CLAIM_STATUS_WORDS[claim.status],
        main_badge=_badge(found.main) if found.main else None,
        other_badges=[_badge(b) for b in found.others],
        confidence=shown,
        source=SourceCard(
            source_id=fact.source.source_id,
            publisher_class=fact.source.publisher_class.value,
            title=fact.source.title,
            url=fact.source.url,
            published_date=fact.source.published_date,
            retrieved_at=fact.source.retrieved_at.isoformat(),
        ),
    )


def slot_row(result: Mapping[str, Any], slot: SlotDef) -> SlotRow:
    """One coverage-grid row from a `slot_result` row (LLD-1 §7.4)."""
    status = SlotStatus(result["status"])
    return SlotRow(
        slot_id=slot.slot_id,
        dimension=slot.dimension,
        question=slot.question,
        headline=slot.headline,
        status=status.value,
        status_word=SLOT_STATUS_WORDS[status],
        flags=list(result.get("flags") or []),
        gap_note=result.get("gap_note"),
        best_claim_ids=list(result.get("best_claim_ids") or []),
        queries=len(result.get("queries_tried") or []),
        sources=len(result.get("sources_checked") or []),
        replans_used=int(result.get("replans_used") or 0),
    )


def summary(
    rows: Sequence[SlotRow],
    cards: Mapping[str, FactCard],
    topics: SummaryTopics | None = None,
) -> dict[str, list[FactCard]]:
    """Per dimension, each slot's best fact with High or Medium confidence, the headline
    slot first, up to SUMMARY_PER_DIMENSION (HD-08: Low confidence never summarises).
    With `topics`, the best such fact on a topic of the brief (D4-3)."""
    by_dimension: dict[str, list[FactCard]] = defaultdict(list)
    for row in sorted(rows, key=lambda r: (not r.headline, r.slot_id)):
        best = next(
            (
                cards[i]
                for i in row.best_claim_ids
                if i in cards
                and cards[i].confidence is not None
                and cards[i].confidence.label != ConfidenceLabel.LOW.value  # type: ignore[union-attr]
                and (topics is None or topics.admits(cards[i], row.dimension))
            ),
            None,
        )
        if best is not None and len(by_dimension[row.dimension]) < SUMMARY_PER_DIMENSION:
            by_dimension[row.dimension].append(best)
    return {d: by_dimension[d] for d in sorted(by_dimension)}


def handle_with_care(
    summarised: Iterable[FactCard],
    facts: Sequence[StoredFact],
    cards: Mapping[str, FactCard],
    contested_pairs: Iterable[tuple[str, str]],
) -> list[CareItem]:
    """LLD-2 §16.6: summary facts that are not city-level or outdated; a person's role
    resting on one source; and every contested pair, both sides together."""
    reasons: dict[str, list[str]] = defaultdict(list)
    for card in summarised:
        if card.main_badge and card.main_badge.code in (Badge.NOT_CITY_LEVEL, Badge.OUTDATED):
            reasons[card.claim_id].append(f"In the summary, but {card.main_badge.label.lower()}")
    leads: dict[tuple[str, str], list[StoredFact]] = defaultdict(list)
    for fact in facts:
        if fact.relation and fact.relation.relation_type is RelationType.LEADS:
            leads[(fact.relation.subject_entity_id, fact.relation.object_entity_id)].append(fact)
    for group in leads.values():
        if len({f.source.source_id for f in group}) == 1:
            for fact in group:
                reasons[fact.claim.claim_id].append("Who leads it rests on a single source")
    for a, b in contested_pairs:
        for claim_id in (a, b):  # both sides of a disagreement, always together
            reasons[claim_id].append("Sources disagree")
    return [
        CareItem(card=cards[claim_id], reason="; ".join(dict.fromkeys(why)))
        for claim_id, why in reasons.items()
        if claim_id in cards
    ]
