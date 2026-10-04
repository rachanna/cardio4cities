"""Retrieval evaluation (LLD-5 §12; D3-2b, BD-39). `poe eval-rag` costs money: ask first.

Loads the fictional Halden Bay fixture (`tests/fixtures/retrieval/halden_bay/`) into
Postgres, the Neo4j graph and a claim index, puts every question through the real
question-answering pipeline, and measures the LLD-5 §12.3 gates: zero scope violations;
100% abstention correctness, contested completeness and citation validity; bundle recall
of at least 0.95 (fixtures) or 0.90 (a real city); first-pass survival is monitored.

In CI (`tests/acceptance/test_retrieval_eval.py`, AT-47) the classifier output is fixed
per question, embeddings are deterministic, and the answerer is scripted twice: faithful,
and faulty (one side of a disagreement, an invented number and person, a wider-area
figure stated as the city's). The gates must hold both times, so the post-check is what
enforces them.

    uv run poe eval-rag [--max-usd 0.30]          # the fixture, with the profile's models
    uv run poe eval-rag --real FILE [--max-usd]  # a researched city: FILE is git-ignored

The fixture run uses the test database (its name must end in `_test`; its schema is
rebuilt) and the profile's graph, under the fixture city's own partition, removed after.
A real-city FILE (YAML: `city_id`, then `questions` with `question`, `gold` claim IDs and
`expect`) runs against the profile's stores; its report goes to the git-ignored
`spike_results/`, since it names a real place.
"""

import argparse
import asyncio
import os
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import yaml

from app.domain.cards import fact_card
from app.domain.entity_names import normalized_key
from app.domain.ids import graph_uuid
from app.domain.models import (
    CityIdentity,
    Claim,
    Entity,
    Labels,
    Relation,
    Source,
    Statistic,
    StoredFact,
    Verdict,
)
from app.domain.params import BadgeParams, ConfidenceParams
from app.domain.vocab import ClaimStatus
from app.ports.embeddings import EmbeddingsPort
from app.ports.graph import GraphEdge, GraphEntity, GraphPort
from app.ports.repos import RelationalPort
from app.ports.vector import VectorPoint, VectorPort
from app.prompts.answerer.schema import AnswererOutput, AnswerSentence
from app.prompts.classifier.schema import ClassifierOutput
from app.query.pipeline import AnswerOutcome, answer_question
from app.query.postcheck import Evidence, numbers_ok
from app.query.types import AskDeps, AskParams, ModelRole
from app.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "retrieval" / "halden_bay"
RESULTS = ROOT / "tests" / "fixtures" / "retrieval" / "results"
CITY_ID = "city_rag_halden_bay"
SHOWN = {"supported", "contested"}
VERDICT_FOR = {
    "supported": "supported",
    "contested": "supported",
    "superseded": "supported",
    "refuted": "refuted",
    "insufficient": "insufficient",
}


def load_yaml(name: str) -> Any:
    return yaml.safe_load((FIXTURE / name).read_text(encoding="utf-8"))


# --- loading the fixture into the stores -----------------------------------------------------


def _dates(period: Any) -> tuple[date | None, date | None]:
    if period is None:
        return None, None
    first, last = (period, period) if not isinstance(period, list) else period
    return date(int(first), 1, 1), date(int(last), 12, 31)


def _claim(raw: Mapping[str, Any], city_id: str, run_id: str) -> Claim:
    start, end = _dates(raw.get("period"))
    labels = Labels(
        geography_level=raw.get("level", "city_wide"),
        geography_name=raw.get("geography", "Halden Bay"),
        measure_type="measured_prevalence" if raw.get("value") else "qualitative",
        reference_start=start,
        reference_end=end,
        reference_precision="year" if start else None,
        period_type="period" if start else "point_in_time",
        population_age_min=18 if raw.get("value") else None,
        representativeness=raw.get("representativeness", "representative_sample"),
        denominator_stated=True,
    )
    return Claim(
        claim_id=raw["id"],
        run_id=run_id,
        city_id=city_id,
        slot_id=raw["slot"],
        source_id=raw["source"],
        kind="relation"
        if raw.get("relation")
        else "statistic"
        if raw.get("value")
        else "statement",
        statement=raw["statement"],
        quote=raw["quote"],
        quote_lang="en",
        quote_translation=None,
        span_start=0,
        span_end=len(raw["quote"]),
        labels=labels,
        status=raw.get("status", "supported"),
        extractor_model="fixture",
        prompt_version="fixture",
    )


async def _city(store: RelationalPort, gazetteer_id: str) -> CityIdentity:
    place = await store.reference.place_identity(gazetteer_id)
    if place is None:
        raise RuntimeError("load the fictional gazetteer first")
    identity = CityIdentity(city_id=CITY_ID, admin2_name=None, **place)
    await store.runs.create_city(identity)
    return identity


async def load_fixture(
    store: RelationalPort,
    graph: GraphPort,
    vector: VectorPort,
    embeddings: EmbeddingsPort,
    claim_collection: str,
) -> dict[str, Any]:
    """Writes the fixture as a finished run would leave it. Returns the run IDs and the
    claims' stored statuses. The gazetteer, slots and indicators must be loaded first."""
    raw = load_yaml("fixture.yaml")
    city = raw["city"]
    await _city(store, city["gazetteer_id"])
    runs = {"old": city["old_run_id"], "latest": city["run_id"]}
    for run_id in (runs["old"], runs["latest"]):
        await store.runs.create_run(run_id, CITY_ID, {}, {})
        if run_id == runs["latest"]:
            break
        await store.runs.set_status(run_id, "completed")
    for s in raw["sources"]:
        for run_id in runs.values():
            await store.sources.add_source(
                Source(
                    source_id=s["id"] if run_id == runs["latest"] else f"{s['id']}_old",
                    run_id=run_id,
                    url=f"https://health.halden-bay.test/{s['id']}",
                    url_canonical=f"https://health.halden-bay.test/{s['id']}/{run_id}",
                    domain="health.halden-bay.test",
                    kind="web_html",
                    publisher_class=s["publisher"],
                    title=s["title"],
                    language="en",
                    published_date=None,
                    published_precision=None,
                    retrieved_at=datetime(2026, 10, 1, tzinfo=UTC),
                    http_status=200,
                    content_type="text/html",
                    content_sha256=None,
                    size_bytes=None,
                    parse_outcome=None,
                    found_via="fixture",
                ),
                None,
                None,
            )
    entities: dict[str, Entity] = {}
    for key, e in raw["entities"].items():
        entity_id = f"ent_rag_{key}"
        entity = Entity(
            entity_id=entity_id,
            city_id=CITY_ID,
            entity_type=e["type"],
            canonical_name=e["name"],
            normalized_key=normalized_key(e["name"]),
            graph_uuid=graph_uuid(entity_id),
            attributes={},
        )
        await store.entities.add_entity(entity)
        for alias in e.get("aliases", []):
            await store.entities.add_alias(CITY_ID, alias, entity_id, "exact", None)
        entities[key] = entity
    statuses: dict[str, str] = {}
    for c in raw["claims"]:
        run_id = runs[c.get("run", "latest")]
        claim = _claim(c, CITY_ID, run_id)
        if run_id != runs["latest"]:
            claim = claim.model_copy(update={"source_id": f"{c['source']}_old"})
        statistic = None
        if c.get("value"):
            statistic = Statistic(
                claim_id=claim.claim_id,
                indicator_code=c["indicator"],
                value_as_written=c["value"],
                value_num=None,
                unit=None,
            )
        relation = None
        if c.get("relation"):
            r = c["relation"]
            relation = Relation(
                claim_id=claim.claim_id,
                subject_entity_id=entities[r["subject"]].entity_id,
                relation_type=r["type"],
                object_entity_id=entities[r["object"]].entity_id,
                valid_from=r.get("valid_from"),
                valid_to=r.get("valid_to"),
            )
        await store.research.add_claim(claim, statistic, relation)
        if relation and c["relation"].get("superseded_on"):
            await store.research.set_superseded_on(claim.claim_id, c["relation"]["superseded_on"])
        status = claim.status.value
        if status in VERDICT_FOR:
            await store.research.add_verdict(
                Verdict(
                    claim_id=claim.claim_id,
                    label=VERDICT_FOR[status],
                    rationale="Fixture.",
                    scope_verified=True,
                    period_verified=True,
                    verifier_model="fixture",
                    verifier_family="fixture",
                    prompt_version="fixture",
                )
            )
        await store.research.refresh_search_tsv(claim.claim_id)
        statuses[claim.claim_id] = status
        if run_id == runs["latest"] and status in SHOWN:
            await _index(vector, embeddings, claim_collection, claim, c.get("indicator"))
        if run_id == runs["latest"] and relation and status in (*SHOWN, "superseded"):
            await _edge(store, graph, claim, relation, entities, c["relation"].get("superseded_on"))
    for a, b in raw["contested"]:
        first, second = sorted((a, b))
        await store.research.add_contested_pair(f"cp_{first}", first, second, a, "fixture")
    for slot_id, row in raw["slot_results"].items():
        await store.runs.save_slot_result(
            runs["latest"],
            {
                "slot_id": slot_id,
                "status": row["status"],
                "flags": row.get("flags", []),
                "replans_used": 0,
                "queries_tried": ["q1", "q2"],
                "sources_checked": ["s1"],
                "best_claim_ids": row.get("best", []),
                "gap_note": row.get("gap_note"),
            },
        )
    await store.runs.set_status(runs["latest"], "completed")
    return {"city_id": CITY_ID, "runs": runs, "statuses": statuses}


async def _index(
    vector: VectorPort,
    embeddings: EmbeddingsPort,
    collection: str,
    claim: Claim,
    indicator: str | None,
) -> None:
    from app.workflow.claim_index import claim_point_id, index_text

    (vec,) = await embeddings.embed([index_text(claim.statement, claim.quote, None)])
    payload = {
        "claim_id": claim.claim_id,
        "city_id": claim.city_id,
        "run_id": claim.run_id,
        "slot_id": claim.slot_id,
        "kind": claim.kind.value,
        "status": claim.status.value,
        "geography_level": claim.labels.geography_level.value,
    }
    if indicator:
        payload["indicator_code"] = indicator
    await vector.ensure_collection(collection, embeddings.dimension)
    await vector.upsert(
        collection, [VectorPoint(id=claim_point_id(claim.claim_id), vector=vec, payload=payload)]
    )


async def _edge(
    store: RelationalPort,
    graph: GraphPort,
    claim: Claim,
    relation: Relation,
    entities: Mapping[str, Entity],
    superseded_on: date | None,
) -> None:
    by_id = {e.entity_id: e for e in entities.values()}

    def node(entity_id: str) -> GraphEntity:
        e = by_id[entity_id]
        return GraphEntity(
            uuid=e.graph_uuid,
            group_id=CITY_ID,
            entity_type=e.entity_type.value,
            name=e.canonical_name,
            attributes={"entity_id": e.entity_id},
        )

    edge = GraphEdge(
        uuid=graph_uuid(claim.claim_id),
        group_id=CITY_ID,
        name=relation.relation_type.value,
        fact=claim.statement,
        valid_at=relation.valid_from,
        invalid_at=relation.valid_to or superseded_on,
        attributes={
            "claim_ids": [claim.claim_id],
            "source_ids": [claim.source_id],
            "status": claim.status.value,
            "proxy_date": False,
        },
    )
    await graph.add_triplet(node(relation.subject_entity_id), edge, node(relation.object_entity_id))
    await store.research.add_graph_link(claim.claim_id, edge.uuid)


# --- scripted models for CI ------------------------------------------------------------------

_FACT = re.compile(
    r"\[(clm_\w+)\] FACT: (.*?) \| value .*? \| slot (S\d\d) \| contested_with: (\S+)"
)
_GAP = re.compile(r"^- (S\d\d): ", re.M)


def _facts(user: str) -> list[tuple[str, str, str, str | None]]:
    """(claim, statement, slot, partner) for each FACT line the answerer was shown."""
    return [
        (c, s.strip(), slot, None if p == "none" else p) for c, s, slot, p in _FACT.findall(user)
    ]


def faithful(asked: Sequence[str]) -> Callable[[str], AnswererOutput]:
    """States the stored statement of each fact of a slot asked about (or the first fact
    when the question named no slot), and abstains for each gap."""

    def answer(user: str) -> AnswererOutput:
        facts = _facts(user)
        chosen = [f for f in facts if f[2] in asked] if asked else facts[:1]
        sentences = [
            AnswerSentence(text=s, refs=[c], kind="fact", slot_id=slot) for c, s, slot, _ in chosen
        ]
        if not asked and chosen and chosen[0][3]:  # its partner too, as a faithful writer would
            partner = next((f for f in facts if f[0] == chosen[0][3]), None)
            if partner:
                sentences.append(
                    AnswerSentence(
                        text=partner[1], refs=[partner[0]], kind="fact", slot_id=partner[2]
                    )
                )
        gaps = _GAP.findall(user.split("gaps:")[-1])
        sentences += [
            AnswerSentence(text="Not found.", refs=[], kind="abstain", slot_id=g) for g in gaps
        ]
        return AnswererOutput(sentences=sentences[:8])

    return answer


def faulty(asked: Sequence[str]) -> Callable[[str], AnswererOutput]:
    """Writes what the post-check exists to stop: one side of a disagreement, a wider-area
    figure stated as the city's, an invented number and an invented person."""

    def answer(user: str) -> AnswererOutput:
        facts = _facts(user)
        chosen = [f for f in facts if f[2] in asked] if asked else facts[:1]
        sentences: list[AnswerSentence] = []
        cited: set[str] = set()
        for c, s, slot, partner in chosen:
            if partner and partner in cited:
                continue  # one side only
            cited.add(c)
            if s.startswith("In Norvania"):
                s = "In Halden Bay" + s[len("In Norvania") :]  # the national figure as the city's
            sentences.append(AnswerSentence(text=s, refs=[c], kind="fact", slot_id=slot))
        anchor = [chosen[0][0]] if chosen else []
        sentences.append(
            AnswerSentence(
                text="In Halden Bay, 77.7% of adults agreed.",
                refs=anchor,
                kind="fact",
                slot_id=asked[0] if asked else None,
            )
        )
        for g in _GAP.findall(user.split("gaps:")[-1]):
            sentences.append(
                AnswerSentence(
                    text="Dr Mira Solberg is responsible for it.",
                    refs=anchor,
                    kind="fact",
                    slot_id=g,
                )
            )
        return AnswererOutput(sentences=sentences[:8])

    return answer


@dataclass
class ScriptedModels:
    """An LLM port answering the classifier from the case and the answerer by script."""

    classified: ClassifierOutput | None = None
    answerer: Callable[[str], AnswererOutput] | None = None
    calls: int = 0

    async def complete(
        self, role: str, system: str, user: str, schema: type[Any], params: Any
    ) -> Any:
        from app.ports.llm import LLMResult

        self.calls += 1
        if role == "classifier":
            parsed: Any = self.classified
        else:
            assert self.answerer is not None  # noqa: S101 - set before every question
            parsed = self.answerer(user)
        return LLMResult(
            parsed=parsed,
            raw_text=parsed.model_dump_json(),
            model_id="scripted",
            family="scripted",
            tokens_in=10,
            tokens_out=10,
            cost_micro_usd=0,
        )


def classified(case: Mapping[str, Any]) -> ClassifierOutput:
    values: dict[str, Any] = {
        "question_type": "open",
        "slot_ids": [],
        "indicator_codes": [],
        "entity_mentions": [],
        "as_of": None,
        "sub_questions": [],
        "refers_to_previous": False,
    }
    values.update(case["classified"])
    return ClassifierOutput(**values)


# --- running and measuring --------------------------------------------------------------------


@dataclass
class Result:
    case: Mapping[str, Any]
    outcome: AnswerOutcome
    bundle: list[str]


@dataclass
class Metrics:
    questions: int = 0
    scope_violations: list[str] = field(default_factory=list)
    abstention: list[bool] = field(default_factory=list)
    contested: list[bool] = field(default_factory=list)
    citations: list[bool] = field(default_factory=list)
    gold_found: int = 0
    gold_all: int = 0
    survival: list[float] = field(default_factory=list)
    misses: list[str] = field(default_factory=list)

    @staticmethod
    def rate(values: Sequence[bool]) -> float:
        return sum(values) / len(values) if values else 1.0

    @property
    def recall(self) -> float:
        return self.gold_found / self.gold_all if self.gold_all else 1.0

    def gates(self, recall_min: float) -> dict[str, bool]:
        return {
            "scope violations: 0": not self.scope_violations,
            "abstention correctness: 100%": self.rate(self.abstention) == 1.0,
            "contested completeness: 100%": self.rate(self.contested) == 1.0,
            "citation validity: 100%": self.rate(self.citations) == 1.0,
            f"bundle recall: >= {recall_min:.2f}": self.recall >= recall_min,
        }


async def measure(
    results: Sequence[Result],
    store: RelationalPort,
    latest_run: str,
    city_id: str,
    pairs: Sequence[tuple[str, str]],
    cards: Callable[[StoredFact], Any],
) -> Metrics:
    m = Metrics(questions=len(results))
    partner = {a: b for a, b in pairs} | {b: a for a, b in pairs}
    for r in results:
        name = r.case.get("id", r.case["question"])
        u = r.outcome.understanding
        allow_superseded = u.question_type == "change_over_time" or u.as_of is not None
        stored = await store.research.stored_facts(r.bundle)
        for claim_id in r.bundle:  # LLD-5 §5, checked again from Postgres
            f = stored.get(claim_id)
            ok = (
                f is not None
                and f.claim.city_id == city_id
                and f.claim.run_id == latest_run
                and (
                    f.claim.status.value in SHOWN
                    or (allow_superseded and f.claim.status is ClaimStatus.SUPERSEDED)
                )
                and f.verdict is not None
                and f.verdict.label.value == "supported"
            )
            if not ok:
                m.scope_violations.append(f"{name}: {claim_id}")
        facts = [s for s in r.outcome.sentences if s.kind in ("fact", "analysis")]
        expect = r.case.get("expect", "answer")
        m.abstention.append(not facts if expect == "abstain" else bool(facts))
        if (expect == "abstain") == bool(facts):
            m.misses.append(f"{name}: expected {expect}, got {len(facts)} fact sentence(s)")
        cited = {ref for s in facts for ref in s.refs}
        for c in cited & partner.keys():
            both = partner[c] in cited
            m.contested.append(both)
            if not both:
                m.misses.append(f"{name}: {c} cited without its partner")
        sentence_facts = await store.research.stored_facts(sorted(cited))
        for s in facts:
            evidence = [
                Evidence(sentence_facts[ref], cards(sentence_facts[ref]))
                for ref in s.refs
                if ref in sentence_facts
            ]
            valid = bool(s.refs) and set(s.refs) <= set(r.bundle) and numbers_ok(s.text, evidence)
            m.citations.append(valid)
            if not valid:
                m.misses.append(f"{name}: an invalid citation in {s.text!r}")
        gold = list(r.case.get("gold") or [])
        found = [g for g in gold if g in r.bundle]
        m.gold_found += len(found)
        m.gold_all += len(gold)
        m.misses += [f"{name}: gold {g} not in the bundle" for g in gold if g not in found]
        post = r.outcome.trace.get("post_check")
        if post:
            m.survival.append(float(post["first_pass_survival"]))
    return m


async def ask_all(
    cases: Sequence[Mapping[str, Any]],
    deps_for: Callable[[Mapping[str, Any]], AskDeps],
) -> list[Result]:
    """Every question through the real pipeline; a follow-up gets its predecessor's
    classification as the previous turn (LLD-5 §3.2)."""
    results: list[Result] = []
    hints: dict[str, Any] = {}
    for case in cases:
        previous = hints.get(case["follows"]) if case.get("follows") else None
        outcome = await answer_question(deps_for(case), case["question"], previous)
        hints[case.get("id", case["question"])] = outcome.understanding.hint()
        results.append(Result(case, outcome, list(outcome.trace.get("bundle", []))))
    return results


def report(title: str, m: Metrics, recall_min: float, extra: Sequence[str] = ()) -> str:
    gates = m.gates(recall_min)
    survival = sum(m.survival) / len(m.survival) if m.survival else 1.0
    lines = [
        f"# {title}",
        "",
        *extra,
        f"- questions: {m.questions}",
        f"- scope violations: {len(m.scope_violations)}",
        f"- abstention correctness: {m.rate(m.abstention):.0%}",
        f"- contested completeness: {m.rate(m.contested):.0%}"
        f" ({len(m.contested)} answers citing a contested claim)",
        f"- citation validity: {m.rate(m.citations):.0%} ({len(m.citations)} fact sentences)",
        f"- bundle recall: {m.recall:.2f} ({m.gold_found}/{m.gold_all}; gate {recall_min:.2f})",
        f"- first-pass survival: {survival:.0%}"
        " (monitored; below 80% means revisit the answer prompt)",
        f"- **{'PASS' if all(gates.values()) else 'FAIL'}**",
        "",
        *[f"- {'ok' if ok else 'FAILED'}: {gate}" for gate, ok in gates.items()],
        "",
        "## Misses",
        "",
        *([f"- {x}" for x in m.misses] or ["- none"]),
        *([f"- scope: {x}" for x in m.scope_violations]),
    ]
    return "\n".join(lines) + "\n"


def ask_params(settings: Settings) -> AskParams:
    r = settings.config.retrieval
    return AskParams(
        rrf_k=r.rrf_k,
        r2_top=r.r2_top,
        r2_trigram_min=r.r2_trigram_min,
        r3_top=r.r3_top,
        r3_mentions_top=r.r3_mentions_top,
        max_facts=r.max_facts,
        max_mentions=r.max_mentions,
        max_per_slot=r.max_per_slot,
        mentions_only_if_facts_below=r.mentions_only_if_facts_below,
    )


def card_maker(
    slots: Mapping[str, Any], settings: Settings, today: date
) -> Callable[[StoredFact], Any]:
    badge = BadgeParams(**settings.config.badge.model_dump())
    confidence = ConfidenceParams(**settings.config.confidence.model_dump())
    return lambda f: fact_card(f, slots[f.claim.slot_id], today, badge, confidence)


# --- `poe eval-rag`: real models -----------------------------------------------------------------


async def _real_fixture(settings: Settings, max_usd: float) -> int:
    from app.adapters.graph.graphiti import GraphitiGraph
    from app.adapters.postgres.relational import PostgresRelational
    from app.api.asking import question_ledger, roles_for, stopwords
    from app.container import ADAPTERS
    from scripts.eval_prompts import llm_adapters
    from scripts.reference.yaml_reference import read_indicators, read_slots
    from tests.support.gazetteer import NEAR_TOWN, PLACE, TOWN, sync_gazetteer
    from tests.support.workflow_fakes import MemoryVector

    url = os.environ.get("TEST_DATABASE_URL", "postgresql://c4c:c4c@127.0.0.1:5432/c4c_test")
    if not url.rsplit("/", 1)[-1].endswith("_test"):
        print("eval-rag rebuilds the test database's schema: TEST_DATABASE_URL must end in _test")
        return 2
    await _rebuild(url)
    import importlib

    module, _, attr = ADAPTERS["embeddings"][settings.config.embeddings.provider].partition(":")
    embeddings = getattr(importlib.import_module(module), attr)(settings)
    g = settings.config.graph
    graph = GraphitiGraph(
        settings.secret(g.uri_env),
        settings.secret(g.user_env),
        settings.secret(g.password_env),
        embeddings,
    )
    store = PostgresRelational(url)
    vector = MemoryVector()
    llm = llm_adapters(settings)
    try:
        await store.reference.sync_indicators(read_indicators())
        await store.reference.sync_slots(read_slots())
        await sync_gazetteer(store, PLACE + TOWN + NEAR_TOWN)
        await graph.delete_group(CITY_ID)
        collection = f"claim_index__{embeddings.key}"
        loaded = await load_fixture(store, graph, vector, embeddings, collection)
        slots = {s.slot_id: s for s in await store.reference.slots()}
        indicators = {i.code: i for i in await store.reference.indicators()}
        city = await store.runs.city_identity(CITY_ID)
        spent = question_ledger(3600, int(max_usd * 1e6))  # one ledger for the whole run
        roles: dict[str, ModelRole] = roles_for(settings)

        def deps_for(case: Mapping[str, Any]) -> AskDeps:
            return AskDeps(
                relational=store,
                vector=vector,
                graph=graph,
                embeddings=embeddings,
                embedding_model=settings.config.embeddings.model,
                llm=llm,
                roles=roles,
                ledger=spent,
                params=ask_params(settings),
                badge=BadgeParams(**settings.config.badge.model_dump()),
                confidence=ConfidenceParams(**settings.config.confidence.model_dump()),
                stopwords=stopwords(),
                slots=slots,
                indicators=indicators,
                city=city,
                city_id=CITY_ID,
                run_id=loaded["runs"]["latest"],
                claim_collection=collection,
                chunk_collection=f"source_chunks__{embeddings.key}",
                today=date.today(),
            )

        results = await ask_all(load_yaml("questions.yaml"), deps_for)
        pairs = [tuple(sorted(p)) for p in load_yaml("fixture.yaml")["contested"]]
        metrics = await measure(
            results,
            store,
            loaded["runs"]["latest"],
            CITY_ID,
            pairs,
            card_maker(slots, settings, date.today()),
        )
        text = report(
            f"Retrieval evaluation: fixture, {settings.env} profile",
            metrics,
            0.95,
            [
                f"- classifier {roles['classifier'].params.model};"
                f" answerer {roles['answerer'].params.model};"
                f" embeddings {settings.config.embeddings.model}",
                f"- cost: ${spent.cost_micro_usd / 1e6:.4f} in {spent.model_calls} model calls",
            ],
        )
        RESULTS.mkdir(exist_ok=True)
        (RESULTS / f"{settings.env}-latest.md").write_text(text, encoding="utf-8")
        print(text)
        return 0 if all(metrics.gates(0.95).values()) else 1
    finally:
        await graph.delete_group(CITY_ID)
        await graph.close()
        await store.close()


async def _rebuild(url: str) -> None:
    """Drops and re-creates the test database's schema (never the development one)."""
    import asyncpg
    from alembic import command
    from alembic.config import Config

    scheme, rest = url.split("://", 1)
    conn = await asyncpg.connect(f"{scheme.split('+')[0]}://{rest}", timeout=5)
    try:
        await conn.execute("DROP SCHEMA IF EXISTS c4c CASCADE")
    finally:
        await conn.close()
    config = Config(toml_file=str(ROOT / "pyproject.toml"), attributes={"database_url": url})
    command.upgrade(config, "head")


async def _real_city(settings: Settings, path: Path, max_usd: float) -> int:
    from app.api.asking import question_ledger, roles_for, stopwords
    from app.container import build_container
    from app.workflow.deps import chunk_collection, claim_collection

    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    container = build_container(settings)
    store = container.relational
    if store is None or container.embeddings is None:
        print("the profile's database or embeddings adapter is not available")
        return 2
    try:
        row = await store.runs.city_row(spec["city_id"])
        if row is None or row["latest_run_id"] is None:
            print("that city has no finished run in the configured database")
            return 2
        slots = {s.slot_id: s for s in await store.reference.slots()}
        indicators = {i.code: i for i in await store.reference.indicators()}
        city = await store.runs.city_identity(spec["city_id"])
        spent = question_ledger(3600, int(max_usd * 1e6))
        key = container.embeddings.key

        def deps_for(case: Mapping[str, Any]) -> AskDeps:
            return AskDeps(
                relational=store,
                vector=container.vector,
                graph=container.graph,
                embeddings=container.embeddings,
                embedding_model=settings.config.embeddings.model,
                llm=container.llm,
                roles=roles_for(settings),
                ledger=spent,
                params=ask_params(settings),
                badge=BadgeParams(**settings.config.badge.model_dump()),
                confidence=ConfidenceParams(**settings.config.confidence.model_dump()),
                stopwords=stopwords(),
                slots=slots,
                indicators=indicators,
                city=city,
                city_id=spec["city_id"],
                run_id=row["latest_run_id"],
                claim_collection=claim_collection(key),
                chunk_collection=chunk_collection(key),
                today=date.today(),
            )

        results = await ask_all(spec["questions"], deps_for)
        pairs = await store.research.contested_pairs(row["latest_run_id"])
        metrics = await measure(
            results,
            store,
            row["latest_run_id"],
            spec["city_id"],
            pairs,
            card_maker(slots, settings, date.today()),
        )
        text = report(
            "Retrieval evaluation: a researched city",
            metrics,
            0.90,
            [f"- cost: ${spent.cost_micro_usd / 1e6:.4f}"],
        )
        out = ROOT / "spike_results" / "rag-real-city-latest.md"  # names a real place: git-ignored
        out.parent.mkdir(exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(text)
        return 0 if all(metrics.gates(0.90).values()) else 1
    finally:
        await container.close()


def main() -> int:
    from dotenv import load_dotenv

    from app.settings import load_settings

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--max-usd", type=float, default=0.30)
    parser.add_argument(
        "--real", type=Path, help="a git-ignored question file for a researched city"
    )
    args = parser.parse_args()
    load_dotenv(".env", override=False)
    settings = load_settings()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    if args.real:
        return asyncio.run(_real_city(settings, args.real, args.max_usd))
    return asyncio.run(_real_fixture(settings, args.max_usd))


if __name__ == "__main__":
    sys.exit(main())
