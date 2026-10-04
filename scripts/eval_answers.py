"""Classifier and answerer golden sets (LLD-3 §9; BD-38), run by `scripts/eval_prompts.py`.
The classifier output is validated as `/ask` validates it; the answerer's output goes
through the real post-check, and each case is graded on what survives. The answerer is
shown its facts exactly as the pipeline shows them (`app/query/pipeline.fact_lines`)."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.domain.cards import fact_card
from app.domain.models import Claim, Labels, SlotDef, SourceRef, StoredFact, Verdict
from app.domain.params import BadgeParams, ConfidenceParams
from app.domain.vocab import ClaimKind, ClaimStatus, PublisherClass
from app.prompts.answerer import context as answerer_context
from app.prompts.answerer.schema import AnswererOutput
from app.prompts.classifier import context as classifier_context
from app.prompts.classifier.schema import ClassifierOutput
from app.query.pipeline import fact_lines
from app.query.postcheck import NOT_CONFIRMED, Checked, Context, Evidence, check
from app.query.types import Mention
from app.query.understand import validate

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "prompts" / "golden"
CITY_NAME = "Halden Bay"
TODAY = date(2026, 10, 4)  # fixed, so badges (outdated) never drift with the calendar


def load(name: str) -> list[dict[str, Any]]:
    data: list[dict[str, Any]] = yaml.safe_load((GOLDEN / name).read_text(encoding="utf-8"))
    return data


# --- classifier ------------------------------------------------------------------------------


def classifier_user(case: Mapping[str, Any], slots: list[SlotDef], indicators: list[Any]) -> str:
    return classifier_context.build_user_message(
        CITY_NAME, slots, indicators, TODAY, case.get("previous"), case["question"]
    )


def classifier_problems(
    case: Mapping[str, Any], out: ClassifierOutput, slot_ids: list[str], codes: list[str]
) -> list[str]:
    u = validate(out, slot_ids, codes)
    problems = []
    if u.question_type not in case["types"]:
        problems.append(f"type {u.question_type}, wanted one of {case['types']}")
    missing = [s for s in case.get("slots", []) if s not in u.slot_ids]
    if missing:
        problems.append(f"slots {list(u.slot_ids)} lack {missing}")
    mention = case.get("mention")
    if mention and not any(m.text.strip() == mention for m in u.entity_mentions):
        problems.append(f"{mention!r} not copied as written")
    prefix = case.get("as_of_prefix")
    if prefix and not (out.as_of or "").startswith(str(prefix)):
        problems.append(f"as_of {out.as_of!r}, wanted {prefix}...")
    if case.get("follow_up") and not u.refers_to_previous:
        problems.append("not marked as a follow-up")
    if len(u.sub_questions) < int(case.get("min_sub_questions", 0)):
        problems.append(f"{len(u.sub_questions)} sub-questions")
    return problems


# --- answerer --------------------------------------------------------------------------------


@dataclass
class Bundle:
    evidence: dict[str, Evidence]
    partners: dict[str, str]
    mentions: list[Mention]
    gaps: list[answerer_context.GapLine]
    ctx: Context


def _fact(raw: Mapping[str, Any]) -> StoredFact:
    year = raw.get("period")
    claim = Claim(
        claim_id=raw["ref"], run_id="run_golden", city_id="city_golden", slot_id=raw["slot"],
        source_id=f"src_{raw['ref']}",
        kind=ClaimKind.STATISTIC if raw.get("value") else ClaimKind.STATEMENT,
        statement=raw["statement"], quote=raw["quote"], quote_lang="en", quote_translation=None,
        span_start=0, span_end=len(raw["quote"]),
        labels=Labels(
            geography_level=raw["level"], geography_name=raw["geography"],
            measure_type="qualitative" if not raw.get("value") else "measured_prevalence",
            reference_start=date(int(year), 1, 1) if year else None,
            reference_end=date(int(year), 12, 31) if year else None,
            reference_precision="year" if year else None, period_type="period",
            representativeness="representative_sample", denominator_stated=True,
        ),
        status=ClaimStatus(raw.get("status", "supported")),
        extractor_model="golden", prompt_version="golden",
    )  # fmt: skip
    return StoredFact(
        claim=claim,
        value_as_written=raw.get("value"),
        verdict=Verdict(
            claim_id=claim.claim_id, label="supported", rationale="Golden case.",
            scope_verified=True, period_verified=True, verifier_model="golden",
            verifier_family="golden", prompt_version="golden",
        ),
        source=SourceRef(
            source_id=claim.source_id, url="https://health.halden-bay.test/golden",
            title="Halden Bay Health Office report", publisher_class=PublisherClass.GOVERNMENT,
            published_date=None, retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
        ),
    )  # fmt: skip


def bundle(
    case: Mapping[str, Any],
    slots: Mapping[str, SlotDef],
    badge: BadgeParams,
    confidence: ConfidenceParams,
) -> Bundle:
    evidence = {}
    partners = {}
    for raw in case.get("facts") or []:
        fact = _fact(raw)
        card = fact_card(fact, slots[fact.claim.slot_id], TODAY, badge, confidence)
        evidence[fact.claim.claim_id] = Evidence(fact, card)
        if raw.get("contested_with"):
            partners[fact.claim.claim_id] = raw["contested_with"]
    mentions = [
        Mention(m["source_id"], m["char_start"], m["char_start"] + len(m["text"]), m["text"],
                m.get("publisher", "other"))
        for m in case.get("mentions") or []
    ]  # fmt: skip
    gaps = [answerer_context.GapLine(s, n) for s, n in (case.get("gaps") or {}).items()]
    gaps += [answerer_context.GapLine(s, n) for s, n in (case.get("wider") or {}).items()]
    results = {
        s: {"status": "answered_negative", "gap_note": n}
        for s, n in (case.get("gaps") or {}).items()
    }
    results |= {
        s: {"status": "answered_wider_geo", "gap_note": n}
        for s, n in (case.get("wider") or {}).items()
    }
    ctx = Context(
        city_name=CITY_NAME, other_names=("Norvania", "West Coast"), question=case["question"],
        asked=tuple(case.get("asked") or ()), slots=slots, results=results, unavailable={},
    )  # fmt: skip
    return Bundle(evidence, partners, mentions, gaps, ctx)


def answerer_user(case: Mapping[str, Any], b: Bundle) -> str:
    mentions = [
        answerer_context.MentionLine(m.ref_id, m.text, m.publisher_class) for m in b.mentions
    ]
    return answerer_context.build_user_message(
        CITY_NAME, case["question"], fact_lines(b.evidence, b.partners), mentions, b.gaps
    )


def post_check(out: AnswererOutput, b: Bundle) -> Checked:
    return check(out.sentences, b.evidence, {m.ref_id for m in b.mentions}, b.partners, b.ctx)


def answer_problems(case: Mapping[str, Any], checked: Checked) -> list[str]:
    """What is wrong with the answer that survived the post-check (empty: the case passes)."""
    facts = [s for s in checked.sentences if s.kind in ("fact", "analysis")]
    cited = {r for s in facts for r in s.refs}
    text = " ".join(s.text for s in checked.sentences)
    expect = case["expect"]
    wanted = set(case.get("cites") or [])
    problems = []
    if expect == "answer" and not cited & wanted:
        problems.append(f"no fact sentence cites {sorted(wanted)}")
    if expect == "disagree" and not wanted <= cited:
        problems.append("both sides of the disagreement not cited")
    if expect == "wider_area":
        if not cited & wanted:
            problems.append("the wider-area figure is not cited")
        if any(r["check"] == 3 for r in checked.removed):
            problems.append("stated the wider-area figure as the city's")
    if expect in ("abstain", "abstain_or_mention"):
        if facts:
            problems.append("stated a fact although no evidence answers it")
        mentions = [s for s in checked.sentences if s.kind == "mention"]
        if expect == "abstain" and not any(s.kind == "abstain" for s in checked.sentences):
            problems.append("no abstention")
        if any(not any(w in s.text.casefold() for w in NOT_CONFIRMED) for s in mentions):
            problems.append("a mention not marked unconfirmed")
    for slot in case.get("covers") or []:
        if not any(s.slot_id == slot for s in checked.sentences):
            problems.append(f"slot {slot} not covered")
    problems += [f"contains {bad!r}" for bad in case.get("forbid") or [] if bad in text]
    return problems
