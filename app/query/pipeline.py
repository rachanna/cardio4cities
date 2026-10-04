"""Question answering, end to end (LLD-5 §2): understand, four routes in parallel,
re-validate in Postgres, fuse, anchor, assemble, answer, post-check, trace. The caller
stores the answer with its trace."""

import asyncio
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.domain.cards import FactCard, fact_card
from app.domain.models import StoredFact
from app.domain.vocab import ClaimKind
from app.prompts.answerer import context
from app.prompts.answerer.schema import AnswererOutput
from app.prompts.loader import load_prompt
from app.query.bundle import Bundle, assemble
from app.query.fuse import anchor, fuse
from app.query.llm import call
from app.query.postcheck import Checked, Context, Evidence, Sentence, abstention, check
from app.query.revalidate import revalidate
from app.query.routes.graph import GRAPH_TYPES, r4, runs_graph
from app.query.routes.keyword import mentioned_entities, r2
from app.query.routes.semantic import r3
from app.query.routes.structured import r1
from app.query.types import AskDeps, RouteResult, Understanding
from app.query.understand import understand

GRAPH_UNAVAILABLE = "Relationship data is temporarily unavailable."  # LLD-5 §4.4
GRAPH_OFF = "The knowledge graph is switched off for this question."  # R-88, admin only


@dataclass
class AnswerOutcome:
    question_type: str
    sentences: list[Sentence]
    cited: list[str]
    graph_used: bool
    understanding: Understanding
    models: dict[str, str] = field(default_factory=dict)
    trace: dict[str, Any] = field(default_factory=dict)


def _period(card: FactCard) -> str:
    start, end = card.period.start, card.period.end
    if not card.period.stated or not (start or end):
        return "not stated"
    if start and end and start != end:
        return f"{start} to {end}"
    return end or start or "not stated"


def _route_trace(route: RouteResult) -> dict[str, Any]:
    out: dict[str, Any] = {
        "candidates": [[c, rank] for rank, c in enumerate(route.candidates, start=1)],
        "ms": route.ms,
        "status": route.status,
    }
    if route.note:
        out["note"] = route.note
    if route.route == "R3":
        out["mentions"] = [[m.source_id, m.char_start] for m in route.mentions]
    return out


def _classification(u: Understanding) -> dict[str, Any]:
    return {
        **u.hint(),
        "as_of": u.as_of.isoformat() if u.as_of else None,
        "sub_questions": list(u.sub_questions),
        "refers_to_previous": u.refers_to_previous,
        "merged_from_previous": list(u.merged_from_previous),
    }


async def answer_question(
    deps: AskDeps, question: str, previous: Mapping[str, Any] | None
) -> AnswerOutcome:
    u = await understand(deps, question, previous)
    models = {"classifier": u.classified_by or ""}
    trace: dict[str, Any] = {"classification": _classification(u)}
    if u.question_type == "out_of_scope":  # one abstention, no slot (LLD-4 §3.4)
        ctx = Context(deps.city.name, (), question, (), deps.slots, {}, {})
        sentence = abstention(None, ctx)
        trace["stores_read"] = {"postgres": False, "qdrant": False, "neo4j": False}
        return AnswerOutcome(u.question_type, [sentence], [], False, u, models, trace)

    store = deps.relational
    city_facts = await store.research.city_facts(deps.city_id)
    entity_ids = await mentioned_entities(deps, question, u)
    routes = await asyncio.gather(
        r1(deps, u, city_facts),
        r2(deps, question, u, entity_ids),
        r3(deps, question, city_facts),
        r4(deps, u, entity_ids),
    )
    by_route = {r.route: r for r in routes}
    trace["routes"] = {r.route: _route_trace(r) for r in routes}

    results = {r["slot_id"]: r for r in await store.runs.slot_results(deps.run_id)}
    pairs = await store.research.contested_pairs(deps.run_id)
    found = [c for r in routes for c in r.candidates]
    best = [c for s in u.slot_ids for c in (results.get(s) or {}).get("best_claim_ids") or []]
    partner_ids = [b for a, b in pairs if a in found] + [a for a, b in pairs if b in found]
    stored = await store.research.stored_facts(list(dict.fromkeys([*found, *best, *partner_ids])))

    # Without the graph, relationship and change questions never fall back to relation
    # claims read from Postgres or Qdrant: those parts abstain (RD-06, R-88)
    graph = by_route["R4"]
    unavailable: dict[str, str] = {}
    blocked: set[str] = set()
    if (
        u.question_type in GRAPH_TYPES
        and graph.status in ("unavailable", "skipped")
        and runs_graph(u)
    ):
        why = GRAPH_OFF if not deps.graph_on else GRAPH_UNAVAILABLE
        blocked = {c for c, f in stored.items() if f.claim.kind is ClaimKind.RELATION}
        unavailable = {s: why for s in u.slot_ids if deps.slots[s].relation_types}

    removed: Counter[str] = Counter()
    if blocked:
        removed["graph_unavailable"] = len({c for c in found if c in blocked})
    candidates = [c for c in found if c not in blocked]
    kept, more_removed = revalidate(candidates, stored, u, deps.city_id, deps.run_id)
    removed += more_removed
    extra_valid, _ = revalidate(
        [c for c in [*best, *partner_ids] if c not in blocked], stored, u, deps.city_id, deps.run_id
    )
    valid = set(kept) | set(extra_valid)
    trace["removed"] = dict(removed)

    route_lists: dict[str, list[str]] = {
        r.route: [c for c in r.candidates if c in valid] for r in routes
    }
    fused = fuse(route_lists, kept, stored, deps.slots, deps.params.rrf_k)
    asked = [s for s in u.slot_ids if s not in unavailable]
    anchors = anchor(asked, results, [c for c, _ in fused], valid)
    bundle = assemble(
        u, fused, anchors.injected, valid, stored, pairs, by_route["R3"].mentions, deps.params
    )
    trace["fused"] = [[c, s] for c, s in fused]
    trace["anchored"] = list(anchors.injected)
    trace["gaps_attached"] = sorted({*anchors.gaps, *unavailable})
    trace["bundle"] = list(bundle.facts)
    trace["mentions"] = [m.ref_id for m in bundle.mentions]

    evidence = await _evidence(deps, bundle, stored)
    ctx = Context(
        city_name=deps.city.name,
        other_names=tuple(n for n in (deps.city.country_name, deps.city.admin1_name) if n),
        question=question,
        asked=tuple(u.slot_ids),
        slots=deps.slots,
        results=results,
        unavailable=unavailable,
    )
    gaps = [
        context.GapLine(s, unavailable.get(s) or str(row.get("gap_note") or ""))
        for s, row in {**anchors.gaps, **{s: {} for s in unavailable}}.items()
    ] + [context.GapLine(s, note) for s, note in anchors.wider.items()]
    drafted, answerer = await _draft(deps, question, bundle, evidence, gaps)
    models["answerer"] = answerer
    checked: Checked = check(
        drafted, evidence, {m.ref_id for m in bundle.mentions}, bundle.partners, ctx
    )
    trace["post_check"] = {
        "removed": len(checked.removed),
        "removals": checked.removed,
        "repaired": checked.repaired,
        "first_pass_survival": checked.first_pass_survival,
    }
    graph_used = graph.status == "ok" and runs_graph(u)
    trace["stores_read"] = {
        "postgres": True,
        "qdrant": by_route["R3"].status == "ok",
        "neo4j": graph_used,
    }
    cited = list(dict.fromkeys(r for s in checked.sentences for r in s.refs if r in evidence))
    return AnswerOutcome(u.question_type, checked.sentences, cited, graph_used, u, models, trace)


async def _evidence(
    deps: AskDeps, bundle: Bundle, stored: Mapping[str, StoredFact]
) -> dict[str, Evidence]:
    facts = [stored[c] for c in bundle.facts]
    entity_ids = sorted(
        {
            e
            for f in facts
            if f.relation
            for e in (f.relation.subject_entity_id, f.relation.object_entity_id)
        }
    )
    entities = await deps.relational.entities.get(entity_ids)
    out = {}
    for f in facts:
        card = fact_card(f, deps.slots[f.claim.slot_id], deps.today, deps.badge, deps.confidence)
        names: Sequence[str] = ()
        if f.relation:
            ids = (f.relation.subject_entity_id, f.relation.object_entity_id)
            names = tuple(entities[i].canonical_name for i in ids if i in entities)
        out[f.claim.claim_id] = Evidence(f, card, tuple(names))
    return out


async def _draft(
    deps: AskDeps,
    question: str,
    bundle: Bundle,
    evidence: Mapping[str, Evidence],
    gaps: Sequence[context.GapLine],
) -> tuple[list[Any], str]:
    lines = [
        context.FactLine(
            ref_id=c,
            statement=e.fact.claim.statement,
            value=e.fact.value_as_written,
            level_word=e.card.geography.level_word,
            geography_name=e.card.geography.name,
            period=_period(e.card),
            badge=e.card.main_badge.label if e.card.main_badge else None,
            confidence=e.card.confidence.label if e.card.confidence else "not rated",
            slot_id=e.fact.claim.slot_id,
            contested_with=bundle.partners.get(c),
        )
        for c, e in evidence.items()
    ]
    mentions = [context.MentionLine(m.ref_id, m.text, m.publisher_class) for m in bundle.mentions]
    prompt = load_prompt("answerer")
    user = context.build_user_message(deps.city.name, question, lines, mentions, gaps)
    out, model_id = await call(deps, "answerer", prompt.system, user, AnswererOutput)
    return list(out.sentences), model_id
