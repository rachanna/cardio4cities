"""Report assembly (LLD-2 §16, R-17, HD-07, AT-18). Pure: code places every fact; the
model's linking prose arrives already post-checked, and only cites facts placed here.
Citations are numbered by first appearance, and every number points at a source."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.domain.cards import CareItem, FactCard, SlotRow, handle_with_care, summary
from app.domain.models import SlotDef, StoredFact
from app.domain.ranking import Candidate, rank_key
from app.domain.vocab import SlotStatus
from app.domain.wording import DIMENSION_NAMES

DIMENSIONS = tuple(DIMENSION_NAMES)


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
) -> Report:
    """`facts` are the latest run's facts (`v_city_facts`), `cards` their FactCards,
    `rows` its slot results. `intros` and `analysis` are post-checked prose, or nothing."""
    by_id = {f.claim.claim_id: f for f in facts}
    citations = _Citations(by_id)
    by_dimension = summary(rows, cards)  # step 2: High or Medium only (HD-08)
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
    for d in DIMENSIONS:  # step 3: every fact, ranked, with badge, confidence and citation
        blocks = tuple(
            SlotBlock(
                row,
                tuple(
                    Cited(cards[f.claim.claim_id], citations.cite(f.claim.claim_id))
                    for f in ranked(row.slot_id)
                ),
            )
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
