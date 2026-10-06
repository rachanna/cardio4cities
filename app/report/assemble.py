"""Report assembly (LLD-2 §16, R-17, HD-07, AT-18). Pure: code places every fact; the
model's linking prose arrives already post-checked, and only cites facts placed here.
Citations are numbered by first appearance, and every number points at a source."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.domain.cards import (
    CareItem,
    FactCard,
    SlotRow,
    SummaryTopics,
    fold_repeats,
    handle_with_care,
    summary,
)
from app.domain.models import SlotDef, StoredFact
from app.domain.ranking import Candidate, rank_key
from app.domain.vocab import GeographyLevel, SlotStatus
from app.domain.wording import DIMENSION_NAMES

DIMENSIONS = tuple(DIMENSION_NAMES)
# Levels at which a fact is the city's own (D4-3): a question answered by a wider-area fact
# its definition accepts (a national plan for a policy question) is "national applies".
CITY_LEVELS = frozenset(
    level.value
    for level in (
        GeographyLevel.CITY_WIDE,
        GeographyLevel.SUB_CITY_AREA,
        GeographyLevel.SUB_CITY_POPULATION,
    )
)


@dataclass(frozen=True)
class Prose:
    """A post-checked sentence or point of the model's linking text (LLD-3 §8)."""

    text: str
    refs: tuple[str, ...]
    kind: str  # fact, analysis, gap; for analysis points: opportunity, risk, gap


@dataclass(frozen=True)
class Cited:
    card: FactCard
    citation: int
    also: tuple[int, ...] = ()  # sources of repeats folded into this fact (D4-3)


@dataclass(frozen=True)
class SlotBlock:
    row: SlotRow
    facts: tuple[Cited, ...]


@dataclass(frozen=True)
class Section:
    dimension: str
    name: str
    intro: tuple[Prose, ...]  # empty when omitted (HD-07)
    slots: tuple[SlotBlock, ...]

    @property
    def answered(self) -> tuple[SlotBlock, ...]:
        """Questions with at least one fact, in catalogue order."""
        return tuple(b for b in self.slots if b.facts)

    @property
    def open(self) -> tuple[SlotRow, ...]:
        """Questions this run did not establish; their gap notes appear once, at the end."""
        return tuple(b.row for b in self.slots if not b.facts)


@dataclass(frozen=True)
class CoverageRow:
    """One dimension's questions by outcome, for the overview (D4-3)."""

    dimension: str
    name: str
    city_level: int
    national_applies: int  # answered by a wider-area fact the question accepts (D4-3)
    wider_area: int
    not_found: int
    blocked_or_unreachable: int


@dataclass(frozen=True)
class SourceEntry:
    number: int
    title: str | None
    publisher_class: str
    url: str
    published_date: date | None
    retrieved_at: str


@dataclass(frozen=True)
class CareEntry:
    item: CareItem
    citation: int


@dataclass(frozen=True)
class Report:
    city_name: str
    country_name: str
    region_name: str | None
    run_id: str
    run_status: str
    run_date: datetime | None
    models: Mapping[str, str]
    counts: Mapping[str, Any]
    summary: tuple[tuple[str, str, tuple[Cited, ...]], ...]  # (dimension, name, facts)
    sections: tuple[Section, ...]
    analysis: tuple[Prose, ...]
    gaps: tuple[SlotRow, ...]
    care: tuple[CareEntry, ...]
    sources: tuple[SourceEntry, ...]
    citation_of: Mapping[str, int] = field(default_factory=dict)  # claim -> number

    @property
    def coverage(self) -> tuple[CoverageRow, ...]:
        rows = []
        for s in self.sections:
            statuses = [b.row.status for b in s.slots]
            answered = [b for b in s.slots if b.row.status == SlotStatus.ANSWERED.value]
            own = sum(
                bool(b.facts) and b.facts[0].card.geography.level in CITY_LEVELS for b in answered
            )
            rows.append(
                CoverageRow(
                    s.dimension,
                    s.name,
                    own,
                    len(answered) - own,
                    statuses.count(SlotStatus.ANSWERED_WIDER_GEO.value),
                    statuses.count(SlotStatus.ANSWERED_NEGATIVE.value),
                    statuses.count(SlotStatus.BLOCKED.value)
                    + statuses.count(SlotStatus.UNREACHABLE.value),
                )
            )
        return tuple(rows)

    @property
    def totals(self) -> CoverageRow:
        c = self.coverage
        return CoverageRow(
            "", "All", sum(r.city_level for r in c), sum(r.national_applies for r in c),
            sum(r.wider_area for r in c), sum(r.not_found for r in c),
            sum(r.blocked_or_unreachable for r in c),
        )  # fmt: skip

    def cite(self, refs: Sequence[str]) -> str:
        """A space then "[1][3]" for the claims a sentence rests on; nothing for none."""
        numbers = dict.fromkeys(self.citation_of[r] for r in refs if r in self.citation_of)
        return (" " + "".join(f"[{n}]" for n in numbers)) if numbers else ""


class _Citations:
    """Numbers sources by first appearance; a fact is cited by its source's number."""

    def __init__(self, facts: Mapping[str, StoredFact]) -> None:
        self._facts = facts
        self.numbers: dict[str, int] = {}  # source -> number
        self.of_claim: dict[str, int] = {}

    def cite(self, claim_id: str) -> int:
        source = self._facts[claim_id].source.source_id
        number = self.numbers.setdefault(source, len(self.numbers) + 1)
        self.of_claim[claim_id] = number
        return number


def assemble(
    city: Mapping[str, Any],
    run: Mapping[str, Any],
    rows: Sequence[SlotRow],
    facts: Sequence[StoredFact],
    cards: Mapping[str, FactCard],
    pairs: Sequence[tuple[str, str]],
    slots: Mapping[str, SlotDef],
    intros: Mapping[str, Sequence[Prose]] | None = None,
    analysis: Sequence[Prose] = (),
    topics: SummaryTopics | None = None,
) -> Report:
    """`facts` are the latest run's facts (`v_city_facts`), `cards` their FactCards,
    `rows` its slot results. `intros` and `analysis` are post-checked prose, or nothing."""
    by_id = {f.claim.claim_id: f for f in facts}
    citations = _Citations(by_id)
    by_dimension = summary(rows, cards, topics)  # step 2: High or Medium, on topic (HD-08, D4-3)
    summarised = tuple(
        (
            d,
            DIMENSION_NAMES[d],
            tuple(Cited(c, citations.cite(c.claim_id)) for c in by_dimension[d]),
        )
        for d in DIMENSIONS
        if d in by_dimension
    )

    def ranked(slot_id: str) -> list[StoredFact]:
        accepted = slots[slot_id].accepted_levels
        mine = [f for f in facts if f.claim.slot_id == slot_id]
        return sorted(
            mine, key=lambda f: rank_key(Candidate(f.claim, f.source.publisher_class), accepted)
        )

    sections = []

    def cited(slot_id: str) -> tuple[Cited, ...]:
        """Ranked facts, each once: a repeat adds its source's number (D4-3)."""
        folded = fold_repeats([cards[f.claim.claim_id] for f in ranked(slot_id)])
        return tuple(
            Cited(
                card,
                citations.cite(card.claim_id),
                tuple(dict.fromkeys(citations.cite(r.claim_id) for r in repeats)),
            )
            for card, repeats in folded
        )

    for d in DIMENSIONS:  # step 3: every fact, ranked, with badge, confidence and citation
        blocks = tuple(
            SlotBlock(row, cited(row.slot_id))
            for row in sorted(rows, key=lambda r: r.slot_id)
            if row.dimension == d
        )
        intro = tuple((intros or {}).get(d, ()))
        sections.append(Section(d, DIMENSION_NAMES[d], intro, blocks))
    care = tuple(  # step 6
        CareEntry(item, citations.cite(item.card.claim_id))
        for item in handle_with_care(
            [c.card for _, _, cs in summarised for c in cs], facts, cards, pairs
        )
    )
    gaps = tuple(
        r for r in sorted(rows, key=lambda r: r.slot_id) if r.status != SlotStatus.ANSWERED.value
    )
    sources = tuple(
        SourceEntry(
            number=number,
            title=f.source.title,
            publisher_class=f.source.publisher_class.value,
            url=f.source.url,
            published_date=f.source.published_date,
            retrieved_at=f.source.retrieved_at.date().isoformat(),
        )
        for source_id, number in sorted(citations.numbers.items(), key=lambda kv: kv[1])
        for f in [next(x for x in facts if x.source.source_id == source_id)]
    )
    return Report(
        city_name=str(city["name"]),
        country_name=str(city["country_name"]),
        region_name=city.get("admin1_name"),
        run_id=str(run["run_id"]),
        run_status=str(run["status"]),
        run_date=run.get("finished_at") or run.get("started_at"),
        models=dict(run.get("versions") or {}),
        counts=dict(run.get("summary") or {}),
        summary=summarised,
        sections=tuple(sections),
        analysis=tuple(p for p in analysis if all(r in citations.of_claim for r in p.refs)),
        gaps=gaps,
        care=care,
        sources=sources,
        citation_of=dict(citations.of_claim),
    )
