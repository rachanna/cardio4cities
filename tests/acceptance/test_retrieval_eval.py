"""AT-47: the fixture evaluation meets every LLD-5 §12.3 gate (R-99; D3-2b, BD-39). The
Halden Bay fixture is loaded into Postgres, the Neo4j graph and a claim index; every
question goes through the real pipeline with its classification fixed and deterministic
embeddings. The gates must hold with a faithful scripted answerer and with a faulty one,
so the post-check, not the answerer, is what enforces them."""

from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from datetime import date
from typing import Any

import pytest

from app.adapters.postgres.relational import PostgresRelational
from app.api.asking import question_ledger, stopwords
from app.domain.params import BadgeParams, ConfidenceParams
from app.ports.llm import LLMParams
from app.prompts.answerer.schema import AnswererOutput
from app.query.types import AskDeps, ModelRole
from app.settings import load_settings
from app.workflow.claim_index import index_text
from scripts import eval_rag
from scripts.reference.yaml_reference import read_indicators, read_slots
from tests.support.gazetteer import NEAR_TOWN, PLACE, TOWN, sync_gazetteer
from tests.support.thin_slice import reachable_graph
from tests.support.workflow_fakes import HashEmbeddings, MemoryVector

pytestmark = [pytest.mark.db, pytest.mark.stores]
TODAY = date(2026, 10, 4)  # fixed: the outdated badge must not drift with the calendar
SCRIPTED = ModelRole("scripted", "scripted", LLMParams(model="scripted", max_output_tokens=1000))


class MeaningEmbeddings(HashEmbeddings):
    """Hash embeddings, except a question marked `means` embeds as that claim's index
    text: it stands for a question worded unlike any claim (AT-43)."""

    def __init__(self) -> None:
        self.same: dict[str, str] = {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await super().embed([self.same.get(t, t) for t in texts])


@pytest.fixture
async def stores(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> AsyncIterator[dict[str, Any]]:
    settings = load_settings({**valid_env, "DATABASE_URL": migrated})
    await relational.reference.sync_indicators(read_indicators())
    await relational.reference.sync_slots(read_slots())
    await sync_gazetteer(relational, PLACE + TOWN + NEAR_TOWN)
    graph = await reachable_graph()
    await graph.delete_group(eval_rag.CITY_ID)
    embeddings, vector = MeaningEmbeddings(), MemoryVector()
    collection = f"claim_index__{embeddings.key}"
    try:
        loaded = await eval_rag.load_fixture(relational, graph, vector, embeddings, collection)
        claims = {c["id"]: c for c in eval_rag.load_yaml("fixture.yaml")["claims"]}
        for case in eval_rag.load_yaml("questions.yaml"):
            if case.get("means"):
                c = claims[case["means"]]
                embeddings.same[case["question"]] = index_text(c["statement"], c["quote"], None)
        yield {
            "settings": settings, "graph": graph, "vector": vector, "embeddings": embeddings,
            "collection": collection, "loaded": loaded,
        }  # fmt: skip
    finally:
        await graph.delete_group(eval_rag.CITY_ID)
        await graph.close()


async def evaluate(
    relational: PostgresRelational,
    stores: Mapping[str, Any],
    answerer: Callable[[Sequence[str]], Callable[[str], AnswererOutput]],
) -> tuple[eval_rag.Metrics, str]:
    settings = stores["settings"]
    slots = {s.slot_id: s for s in await relational.reference.slots()}
    indicators = {i.code: i for i in await relational.reference.indicators()}
    city = await relational.runs.city_identity(eval_rag.CITY_ID)
    latest = stores["loaded"]["runs"]["latest"]
    r = settings.config.retrieval

    def deps_for(case: Mapping[str, Any]) -> AskDeps:
        classified = eval_rag.classified(case)
        models = eval_rag.ScriptedModels(classified, answerer(classified.slot_ids))
        return AskDeps(
            relational=relational, vector=stores["vector"], graph=stores["graph"],
            embeddings=stores["embeddings"], embedding_model="hash", llm={"scripted": models},
            roles={"classifier": SCRIPTED, "answerer": SCRIPTED},
            ledger=question_ledger(r.wall_clock_s, r.max_cost_micro_usd),
            params=eval_rag.ask_params(settings),
            badge=BadgeParams(**settings.config.badge.model_dump()),
            confidence=ConfidenceParams(**settings.config.confidence.model_dump()),
            stopwords=stopwords(), slots=slots, indicators=indicators, city=city,
            city_id=eval_rag.CITY_ID, run_id=latest, claim_collection=stores["collection"],
            chunk_collection="source_chunks__hash", today=TODAY,
        )  # fmt: skip

    results = await eval_rag.ask_all(eval_rag.load_yaml("questions.yaml"), deps_for)
    pairs = [(a, b) for a, b in eval_rag.load_yaml("fixture.yaml")["contested"]]
    metrics = await eval_rag.measure(
        results, relational, latest, eval_rag.CITY_ID, pairs,
        eval_rag.card_maker(slots, settings, TODAY),
    )  # fmt: skip
    return metrics, eval_rag.report("Retrieval evaluation (CI)", metrics, 0.95)


async def test_the_fixture_evaluation_meets_every_gate_with_a_faithful_answerer(
    relational: PostgresRelational, stores: Mapping[str, Any]
) -> None:
    """AT-47 (R-99): zero scope violations; 100% abstention correctness, contested
    completeness and citation validity; bundle recall of at least 0.95."""
    metrics, report = await evaluate(relational, stores, eval_rag.faithful)
    assert metrics.questions == 25
    assert all(metrics.gates(0.95).values()), report
    assert metrics.recall == 1.0, report
    assert sum(metrics.survival) / len(metrics.survival) == 1.0, report


async def test_the_gates_hold_when_the_answerer_misbehaves(
    relational: PostgresRelational, stores: Mapping[str, Any]
) -> None:
    """AT-47: one side of a disagreement, a wider-area figure stated as the city's, an
    invented number and an invented person are all caught by the post-check."""
    metrics, report = await evaluate(relational, stores, eval_rag.faulty)
    assert all(metrics.gates(0.95).values()), report
    assert sum(metrics.survival) / len(metrics.survival) < 0.8, report  # it did misbehave


async def test_without_the_post_check_the_faulty_answerer_breaks_the_gates(
    relational: PostgresRelational, stores: Mapping[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The gates measure something: with the post-check switched off, the same faulty
    answers fail contested completeness and citation validity."""
    from app.query import pipeline
    from app.query.postcheck import Checked, Sentence

    def no_check(drafted: Sequence[Any], *_: Any) -> Checked:
        return Checked([Sentence(s.text, s.kind, list(s.refs), s.slot_id) for s in drafted])

    monkeypatch.setattr(pipeline, "check", no_check)
    metrics, report = await evaluate(relational, stores, eval_rag.faulty)
    gates = metrics.gates(0.95)
    assert not gates["contested completeness: 100%"], report
    assert not gates["citation validity: 100%"], report


async def test_without_re_validation_rejected_claims_reach_the_bundle(
    relational: PostgresRelational, stores: Mapping[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The scope gate measures something: trusting the indexes lets a refuted, an older
    run's or an unchecked claim into a bundle (LLD-5 §5)."""
    from collections import Counter

    from app.query import pipeline

    def trust_everything(candidates: Sequence[str], *_: Any) -> tuple[list[str], Counter[str]]:
        return list(dict.fromkeys(candidates)), Counter()

    monkeypatch.setattr(pipeline, "revalidate", trust_everything)
    metrics, report = await evaluate(relational, stores, eval_rag.faithful)
    assert metrics.scope_violations, report
