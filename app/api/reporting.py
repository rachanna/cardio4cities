"""Builds a city's report (LLD-2 §16, LLD-3 §8; D3-3, BD-40). Code places every fact; the
reporter model writes only linking prose, which goes through the same checks as answers
(cited facts only, numbers and names from the evidence) and is dropped when it fails, or
when too little survives (HD-07). The report has its own budget ledger (owner, BD-40); a
refused or failed call omits that paragraph, never the report."""

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from fastapi import Request

from app.api import reading
from app.api.asking import question_ledger, roles_for
from app.domain.cards import FactCard, SlotRow, slot_row, summary
from app.domain.models import StoredFact
from app.domain.wording import DIMENSION_NAMES
from app.ports.errors import PortError
from app.prompts.loader import load_prompt
from app.prompts.reporter import context
from app.prompts.reporter.schema import AnalysisOutput, DimensionIntro
from app.query.llm import call
from app.query.postcheck import Context, Evidence, names_ok, numbers_ok
from app.query.types import AskDeps, ModelRole
from app.report import render
from app.report.assemble import Prose, Report, assemble
from app.workflow.budget import BudgetExhaustedError, BudgetLedger

log = logging.getLogger(__name__)
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


@dataclass
class _Deps:
    """The parts of AskDeps that `app/query/llm.call` uses."""

    ledger: BudgetLedger
    llm: Mapping[str, Any]
    roles: Mapping[str, ModelRole]


@dataclass(frozen=True)
class Built:
    report: Report
    markdown: bytes
    html: bytes
    pdf_html: str


def _words(prose: Sequence[Prose]) -> int:
    return sum(len(p.text.split()) for p in prose)


def check_sentences(
    sentences: Sequence[Any],
    evidence: Mapping[str, Evidence],
    gap_text: str,
    ctx: Context,
    max_words: int,
    min_words: int,
) -> tuple[Prose, ...]:
    """LLD-3 §8.5: a fact or analysis sentence cites only facts of its section, and its
    numbers and names come from them; a gap sentence names no number the gap notes do not.
    Kept up to `max_words`; under `min_words` the paragraph is omitted (HD-07)."""
    kept: list[Prose] = []
    for s in sentences:
        refs = tuple(s.refs)
        cited = [evidence[r] for r in refs if r in evidence]
        if s.kind == "gap":
            ok = all(n in gap_text for n in _NUMBER.findall(s.text)) and names_ok(
                s.text, cited, ctx
            )
        else:
            ok = (
                bool(refs) and len(cited) == len(refs)
                and numbers_ok(s.text, cited) and names_ok(s.text, cited, ctx)
            )  # fmt: skip
        if not ok:
            continue
        if _words(kept) + len(s.text.split()) > max_words:
            break
        kept.append(Prose(s.text, refs, s.kind))
    return tuple(kept) if _words(kept) >= min_words else ()


def check_points(
    points: Sequence[Any], evidence: Mapping[str, Evidence], ctx: Context, max_points: int
) -> tuple[Prose, ...]:
    kept = []
    for p in points:
        refs = tuple(p.derived_from)
        cited = [evidence[r] for r in refs if r in evidence]
        if (
            refs
            and len(cited) == len(refs)
            and numbers_ok(p.text, cited)
            and names_ok(p.text, cited, ctx)
        ):
            kept.append(Prose(p.text, refs, p.kind))
    return tuple(kept[:max_points])


async def _prose(
    request: Request,
    city: Mapping[str, Any],
    rows: Sequence[SlotRow],
    facts: Sequence[StoredFact],
    cards: Mapping[str, FactCard],
) -> tuple[dict[str, tuple[Prose, ...]], tuple[Prose, ...], dict[str, Any]]:
    container = request.app.state.container
    cfg = container.settings.config.report
    roles = roles_for(container.settings, ("reporter",))
    if roles["reporter"].provider not in container.llm:
        return {}, (), {"skipped": "no reporter model"}
    ledger = question_ledger(cfg.wall_clock_s, cfg.max_cost_micro_usd)
    deps = cast(AskDeps, _Deps(ledger, container.llm, roles))
    prompt = load_prompt("reporter")
    evidence = {f.claim.claim_id: Evidence(f, cards[f.claim.claim_id]) for f in facts}
    names = tuple(n for n in (city.get("country_name"), city.get("admin1_name")) if n)
    intros: dict[str, tuple[Prose, ...]] = {}
    failures = 0
    for d, name in DIMENSION_NAMES.items():
        mine = [f for f in facts if rows_dimension(rows, f.claim.slot_id) == d]
        gaps = [r.gap_note for r in rows if r.dimension == d and r.gap_note]
        if not mine and not gaps:
            continue
        refs = [
            context.FactRef(f.claim.claim_id, f.claim.statement, _badge(cards[f.claim.claim_id]))
            for f in mine
        ]
        user = context.intro_message(str(city["name"]), name, refs, gaps, cfg.intro_max_words)
        ctx = Context(str(city["name"]), names, " ".join([name, *gaps]), (), {}, {}, {})
        try:
            out, _ = await call(deps, "reporter", prompt.system, user, DimensionIntro)
        except (PortError, BudgetExhaustedError) as exc:
            failures += 1
            log.warning("report: %s introduction omitted (%s)", d, type(exc).__name__)
            continue
        section = {f.claim.claim_id: evidence[f.claim.claim_id] for f in mine}
        intros[d] = check_sentences(
            out.sentences,
            section,
            " ".join(gaps),
            ctx,
            cfg.intro_max_words,
            cfg.min_paragraph_words,
        )
    summarised = [c.claim_id for cards_ in summary(rows, cards).values() for c in cards_]
    analysis: tuple[Prose, ...] = ()
    if summarised:
        refs = [context.FactRef(c, cards[c].statement, _badge(cards[c])) for c in summarised]
        gaps = [r.gap_note for r in rows if r.gap_note]
        user = context.analysis_message(str(city["name"]), refs, gaps, cfg.analysis_max_points)
        ctx = Context(str(city["name"]), names, " ".join(gaps), (), {}, {}, {})
        try:
            out_a, _ = await call(deps, "reporter", prompt.system, user, AnalysisOutput)
            analysis = check_points(
                out_a.points, {c: evidence[c] for c in summarised}, ctx, cfg.analysis_max_points
            )
        except (PortError, BudgetExhaustedError) as exc:
            failures += 1
            log.warning("report: analysis omitted (%s)", type(exc).__name__)
    spent = {
        "model_calls": ledger.model_calls,
        "cost_micro_usd": ledger.cost_micro_usd,
        "failures": failures,
    }
    return intros, analysis, spent


def rows_dimension(rows: Sequence[SlotRow], slot_id: str) -> str | None:
    return next((r.dimension for r in rows if r.slot_id == slot_id), None)


def _badge(card: FactCard) -> str | None:
    return card.main_badge.label if card.main_badge else None


async def build(request: Request, city_row: Mapping[str, Any]) -> Built:
    store = reading.relational(request)
    run_id = str(city_row["latest_run_id"])
    maker = await reading.card_maker(request)
    facts = await store.research.city_facts(str(city_row["city_id"]))
    cards = {f.claim.claim_id: maker.card(f) for f in facts}
    results = await store.runs.slot_results(run_id)
    rows = [slot_row(r, maker.slots[r["slot_id"]]) for r in results if r["slot_id"] in maker.slots]
    pairs = await store.research.contested_pairs(run_id)
    run = await store.runs.run_row(run_id) or {}
    city = dict(city_row["identity"])
    intros, analysis, spent = await _prose(request, city, rows, facts, cards)
    log.info("report for %s: prose %s", run_id, spent)
    report = assemble(city, run, rows, facts, cards, pairs, maker.slots, intros, analysis)
    return Built(
        report=report,
        markdown=render.markdown(report).encode("utf-8"),
        html=render.html(report).encode("utf-8"),
        pdf_html=render.html(report, pdf=True),
    )
