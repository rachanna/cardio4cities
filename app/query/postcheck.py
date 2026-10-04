"""The post-check (LLD-2 §15.1 step 5, LLD-5 §9): code checks every sentence the answerer
wrote. Most failures remove the sentence and abstain for its slot; three are repaired
from stored values only (contested pairs, missing years, missing coverage), so a repair
can never add an error. Abstentions are always written from the stored gap record.
Pure."""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from app.domain.badges import most_severe
from app.domain.cards import BadgeCard, FactCard
from app.domain.geography import effective_level
from app.domain.models import SlotDef, StoredFact
from app.domain.text import normalise_text
from app.domain.vocab import Badge, ClaimStatus, GeographyLevel
from app.domain.wording import BADGE_LABELS, CLAIM_STATUS_WORDS
from app.prompts.answerer.schema import AnswerSentence

Kind = Literal["fact", "mention", "analysis", "abstain"]
NOT_CONFIRMED = ("not confirmed", "unconfirmed", "not been confirmed")  # §15.1: fixed list
# Words that tell a reader a figure describes a wider area (LLD-5 §9 check 3)
LEVEL_STEMS: dict[GeographyLevel, tuple[str, ...]] = {
    GeographyLevel.NATIONAL: ("national", "country"),
    GeographyLevel.STATE_PROVINCE: ("state", "region", "province"),
    GeographyLevel.DISTRICT: ("district",),
    GeographyLevel.METRO_REGION: ("metropolitan", "metro"),
    GeographyLevel.GLOBAL: ("global", "world"),
    GeographyLevel.SUB_CITY_AREA: ("part of", "area", "district", "neighbourhood"),
    GeographyLevel.SUB_CITY_POPULATION: ("group", "among"),
}
_NUMBER = re.compile(r"(?<![\w.,])\d+(?:[.,]\d+)*")
_YEAR = re.compile(r"^(19|20)\d\d$")
_CAPITALISED = r"[A-Z][\w'\u2019&.-]*"  # \u2019: a typographic apostrophe
_PHRASE = re.compile(rf"{_CAPITALISED}(?:\s+(?:of|and|for|the|de|la|&)?\s*{_CAPITALISED})+")
_ACRONYM = re.compile(r"\b[A-Z]{2,8}\b")
_LEADING_THE = re.compile(r"^The\s+")


@dataclass(frozen=True)
class Evidence:
    """What the post-check knows about one bundle fact."""

    fact: StoredFact
    card: FactCard
    entity_names: tuple[str, ...] = ()


@dataclass
class Sentence:
    text: str
    kind: Kind
    refs: list[str]
    slot_id: str | None
    main_badge: BadgeCard | None = None
    status_word: str | None = None
    written_by: Literal["model", "code"] = "model"


@dataclass
class Checked:
    sentences: list[Sentence]
    removed: list[dict[str, Any]] = field(default_factory=list)
    repaired: list[dict[str, Any]] = field(default_factory=list)
    first_pass_survival: float = 1.0


@dataclass(frozen=True)
class Context:
    city_name: str
    other_names: tuple[str, ...]  # country and region names the answer may use
    question: str
    asked: tuple[str, ...]  # slots asked about, in order
    slots: Mapping[str, SlotDef]
    results: Mapping[str, Mapping[str, Any]]  # slot_result rows of the latest run
    unavailable: Mapping[str, str]  # slot -> why its data cannot be read now (RD-06)


# --- abstentions (LLD-2 §15.2) -----------------------------------------------------------


def abstention(slot_id: str | None, ctx: Context) -> Sentence:
    if slot_id is None or slot_id not in ctx.slots:
        return Sentence(
            f"This isn't covered by the research for {ctx.city_name}.", "abstain", [], None,
            written_by="code",
        )  # fmt: skip
    what = ctx.slots[slot_id].short_label
    if slot_id in ctx.unavailable:
        note = ctx.unavailable[slot_id]
    else:
        note = str((ctx.results.get(slot_id) or {}).get("gap_note") or "")
    text = f"No confirmed {what} for {ctx.city_name}. {note}".strip()
    return Sentence(text, "abstain", [], slot_id, written_by="code")


# --- the checks ----------------------------------------------------------------------------


def _numbers(text: str) -> list[str]:
    """Number tokens, except years written alone (LLD-2 §15.1)."""
    out = []
    for m in _NUMBER.finditer(text):
        token = m.group(0)
        after = text[m.end() : m.end() + 2]
        if _YEAR.match(token) and not after.lstrip().startswith("%"):
            continue
        out.append(token)
    return out


def _stands_in(number: str, text: str) -> bool:
    pattern = rf"(?<![\d]){re.escape(number)}(?![\d])(?![.,]\d)"
    return re.search(pattern, text) is not None


def numbers_ok(text: str, cited: Sequence[Evidence]) -> bool:
    """Check 2: every number appears in a cited claim's value or quote (normalised)."""
    sources = " | ".join(
        normalise_text(f"{e.fact.value_as_written or ''} {e.fact.claim.quote}") for e in cited
    )
    return all(_stands_in(normalise_text(n), sources) for n in _numbers(normalise_text(text)))


def wider_area_ok(text: str, cited: Sequence[Evidence], ctx: Context) -> bool:
    """Check 3: a wider-area figure stated together with the city carries its level word
    (or names the wider area)."""
    if ctx.city_name.casefold() not in text.casefold():
        return True
    lowered = text.casefold()
    for e in cited:
        level = effective_level(e.fact.claim)
        if level in ctx.slots[e.fact.claim.slot_id].accepted_levels:
            continue
        words = (*LEVEL_STEMS.get(level, ()), e.fact.claim.labels.geography_name.casefold())
        if not any(w and w.casefold() in lowered for w in words):
            return False
    return True


def names_ok(text: str, cited: Sequence[Evidence], ctx: Context) -> bool:
    """Check 4: every proper name (a run of capitalised words, or an acronym) appears in
    the question, a cited claim, a cited entity's names, or the city's own names (AT-15)."""
    allowed = " | ".join(
        [ctx.question, ctx.city_name, *ctx.other_names]
        + [f"{e.fact.claim.statement} {e.fact.claim.quote} {e.fact.claim.quote_translation or ''}"
           for e in cited]
        + [n for e in cited for n in e.entity_names]
    ).casefold()  # fmt: skip
    names = [_LEADING_THE.sub("", m.group(0)).rstrip(".'-&") for m in _PHRASE.finditer(text)]
    names += _ACRONYM.findall(text)
    return all(n.casefold() in allowed for n in names if n)


def _year(e: Evidence) -> str | None:
    labels = e.fact.claim.labels
    when = labels.reference_end or labels.reference_start
    return str(when.year) if when else None


def _outdated(e: Evidence) -> bool:
    codes = {b.code for b in e.card.other_badges}
    if e.card.main_badge is not None:
        codes.add(e.card.main_badge.code)
    return Badge.OUTDATED.value in codes


def contested_template(a: Evidence, b: Evidence) -> str:
    """Check 5's repair: both sides, from stored values only."""

    def side(e: Evidence) -> str:
        value = e.fact.value_as_written or e.fact.claim.statement.rstrip(".")
        source = e.fact.source.title or e.fact.source.publisher_class.value
        return f"{value} ({source}, {_year(e) or 'year not stated'})"

    return f"Sources disagree: {side(a)} and {side(b)}."


# --- the pass ---------------------------------------------------------------------------


def check(
    drafted: Sequence[AnswerSentence],
    evidence: Mapping[str, Evidence],
    mention_refs: set[str],
    partners: Mapping[str, str],
    ctx: Context,
) -> Checked:
    out = Checked(sentences=[])
    removed_slots: list[str | None] = []
    passed = 0

    def remove(s: AnswerSentence, check_no: int, reason: str) -> None:
        out.removed.append({"check": check_no, "reason": reason, "refs": list(s.refs)})
        slot = s.slot_id or next(
            (evidence[r].fact.claim.slot_id for r in s.refs if r in evidence), None
        )
        removed_slots.append(slot)

    for s in drafted:
        if s.kind == "abstain":  # the wording always comes from the gap record (LLD-3 §7.4)
            out.sentences.append(abstention(s.slot_id, ctx))
            passed += 1
            continue
        if s.kind == "mention":
            if not s.refs or not set(s.refs) <= mention_refs:
                remove(s, 8, "mention cites no mention")
            elif not any(w in s.text.casefold() for w in NOT_CONFIRMED):
                remove(s, 8, "mention not worded as unconfirmed")
            else:
                out.sentences.append(Sentence(s.text, "mention", list(s.refs), s.slot_id))
                passed += 1
            continue
        facts = [r for r in s.refs if r in evidence]
        if not s.refs or len(facts) != len(s.refs):
            remove(s, 1, "cites nothing, or a claim outside the bundle")
            continue
        cited = [evidence[r] for r in facts]
        if not numbers_ok(s.text, cited):
            remove(s, 2, "a number not in its cited claims")
        elif not wider_area_ok(s.text, cited, ctx):
            remove(s, 3, "a wider-area figure stated for the city without its level")
        elif not names_ok(s.text, cited, ctx):
            remove(s, 4, "a name not in the question or the evidence")
        else:
            slot = s.slot_id if s.slot_id in ctx.slots else cited[0].fact.claim.slot_id
            out.sentences.append(Sentence(s.text, s.kind, facts, slot))
            passed += 1

    _repair_contested(out, evidence, partners)
    _repair_years(out, evidence)
    _repair_coverage(out, evidence, ctx)
    covered = {x.slot_id for x in out.sentences}
    for slot in dict.fromkeys(removed_slots):
        if slot not in covered:
            out.sentences.append(abstention(slot, ctx))
            covered.add(slot)
    out.sentences = _dedupe_abstentions(out.sentences)
    for sentence in out.sentences:
        _badge(sentence, evidence)
    out.first_pass_survival = round(passed / len(drafted), 3) if drafted else 1.0
    return out


def _repair_contested(
    out: Checked, evidence: Mapping[str, Evidence], partners: Mapping[str, str]
) -> None:
    """Check 5: a sentence citing one side of a contested pair, while the other side is
    cited nowhere in the answer, becomes the code template with both."""
    cited = {r for s in out.sentences for r in s.refs}
    for i, s in enumerate(out.sentences):
        lone = [r for r in s.refs if r in partners and partners[r] not in cited]
        if s.kind not in ("fact", "analysis") or not lone:
            continue
        a, b = lone[0], partners[lone[0]]
        if b not in evidence:
            continue
        out.sentences[i] = Sentence(
            contested_template(evidence[a], evidence[b]), "fact", [a, b], s.slot_id,
            written_by="code",
        )  # fmt: skip
        cited |= {a, b}
        out.repaired.append({"check": 5, "claims": [a, b]})


def _repair_years(out: Checked, evidence: Mapping[str, Evidence]) -> None:
    """Check 6: a sentence citing an outdated figure gives its year."""
    for s in out.sentences:
        if s.kind not in ("fact", "analysis"):
            continue
        for r in s.refs:
            e = evidence.get(r)
            year = _year(e) if e else None
            if e and _outdated(e) and year and year not in s.text:
                stripped = s.text.rstrip()
                end = stripped[-1] if stripped and stripped[-1] in ".!?" else ""
                body = stripped[:-1] if end else stripped
                s.text = f"{body} (as of {year}){end or '.'}"
                out.repaired.append({"check": 6, "claims": [r]})


def _repair_coverage(out: Checked, evidence: Mapping[str, Evidence], ctx: Context) -> None:
    """Check 7: every slot asked about gets a fact sentence or an abstention. A slot whose
    confirmed fact is in the bundle gets that fact's stored statement (with the gap note
    of a wider-area answer first); otherwise its abstention."""
    covered = {s.slot_id for s in out.sentences} | {
        evidence[r].fact.claim.slot_id for s in out.sentences for r in s.refs if r in evidence
    }
    for slot in ctx.asked:
        if slot in covered or slot not in ctx.slots:
            continue
        found = [e for e in evidence.values() if e.fact.claim.slot_id == slot]
        if found and slot not in ctx.unavailable:
            e = found[0]
            note = (ctx.results.get(slot) or {}).get("gap_note")
            wider = (ctx.results.get(slot) or {}).get("status") == "answered_wider_geo"
            text = f"{note} {e.fact.claim.statement}" if wider and note else e.fact.claim.statement
            out.sentences.append(
                Sentence(text, "fact", [e.fact.claim.claim_id], slot, written_by="code")
            )
            out.repaired.append({"check": 7, "slot": slot, "with": "fact"})
        else:
            out.sentences.append(abstention(slot, ctx))
            out.repaired.append({"check": 7, "slot": slot, "with": "abstention"})
        covered.add(slot)


def _dedupe_abstentions(sentences: list[Sentence]) -> list[Sentence]:
    seen: set[str | None] = set()
    out = []
    for s in sentences:
        if s.kind == "abstain":
            if s.slot_id in seen:
                continue
            seen.add(s.slot_id)
        out.append(s)
    return out


def _badge(s: Sentence, evidence: Mapping[str, Evidence]) -> None:
    """Step 6: the most severe main badge among the sentence's claims, and its status."""
    cited = [evidence[r] for r in s.refs if r in evidence]
    if not cited:
        return
    main = most_severe(Badge(e.card.main_badge.code) if e.card.main_badge else None for e in cited)
    s.main_badge = BadgeCard(code=main.value, label=BADGE_LABELS[main]) if main else None
    statuses = {e.fact.claim.status for e in cited}
    for status in (ClaimStatus.CONTESTED, ClaimStatus.SUPERSEDED, ClaimStatus.SUPPORTED):
        if status in statuses:
            s.status_word = CLAIM_STATUS_WORDS[status]
            break
