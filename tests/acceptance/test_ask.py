"""Question answering end to end (D3-2; LLD-5 §13): AT-10, AT-11, AT-15, AT-28, AT-39,
AT-40, AT-42, AT-43, AT-44, AT-45, AT-46, and AT-13 for answers. The app answers over
the thin slice's real stores (Postgres, the Neo4j graph, an in-memory vector index) with
scripted classifier and answerer models; fictional Halden Bay, Norvania."""

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from app.api.auth import COOKIE_NAME, AccessConfig, issue_token
from app.container import Container
from app.main import create_app
from app.ports.vector import VectorPoint
from app.prompts.answerer.schema import AnswererOutput, AnswerSentence
from app.prompts.classifier.schema import ClassifierOutput, EntityMention
from app.query import pipeline
from app.query.types import RouteResult
from app.workflow.claim_index import claim_point_id, index_text
from tests.acceptance.test_read_api import SECRET  # the test session key the scanner accepts
from tests.support.thin_slice import (
    NEARBY_STATEMENT,
    NEW_GOV_STATEMENT,
    OLD_GOV_STATEMENT,
    TRUE_STATEMENT,
    Slice,
    query_rows,
)
from tests.support.workflow_fakes import HashEmbeddings, ScriptedLLM

pytestmark = [pytest.mark.db, pytest.mark.stores]
_FACT = re.compile(r"\[(clm_\w+)\] FACT: ([^|]*)")


def classified(
    question_type: str = "figure", slots: tuple[str, ...] = ("S04",), **more: Any
) -> ClassifierOutput:
    values: dict[str, Any] = {
        "question_type": question_type,
        "slot_ids": list(slots),
        "indicator_codes": [],
        "entity_mentions": [],
        "as_of": None,
        "sub_questions": [],
        "refers_to_previous": False,
    }
    values.update(more)
    return ClassifierOutput(**values)


def ref(user: str, statement: str) -> str:
    """The claim ID the answerer was shown for a statement."""
    return str(
        next(c for c, text in _FACT.findall(user) if text.strip().startswith(statement[:40]))
    )


def says(text: str, statement: str, slot: str = "S04") -> Callable[[str], AnswererOutput]:
    def answer(user: str) -> AnswererOutput:
        sentence = AnswerSentence(text=text, refs=[ref(user, statement)], kind="fact", slot_id=slot)
        return AnswererOutput(sentences=[sentence])

    return answer


@dataclass
class Script:
    classifier: ClassifierOutput = field(default_factory=classified)
    answerer: Callable[[str], AnswererOutput] = lambda _: AnswererOutput(sentences=[])
    users: list[str] = field(default_factory=list)  # what the answerer was shown


@dataclass
class AskClient:
    client: httpx.AsyncClient
    script: Script
    slice: Slice
    embeddings: Any
    # One session per role, as a browser keeps its cookie: a token issued per question
    # changed whenever a second boundary passed, so the per-session limit saw two sessions
    tokens: dict[str, str] = field(default_factory=dict)

    async def ask(self, question: str, role: str = "viewer", **body: Any) -> httpx.Response:
        token = self.tokens.setdefault(role, issue_token(role, SECRET))  # type: ignore[arg-type]
        self.client.cookies.set(COOKIE_NAME, token)
        return await self.client.post(
            f"/api/v1/cities/{self.slice.city_id}/ask", json={"question": question, **body}
        )

    async def ok(self, question: str, role: str = "admin", **body: Any) -> dict[str, Any]:
        response = await self.ask(question, role, **body)
        assert response.status_code == 200, response.text
        result: dict[str, Any] = response.json()
        return result

    async def claim_id(self, statement: str) -> str:
        (row,) = await query_rows(
            self.slice.store,
            "SELECT claim_id FROM claim WHERE run_id = :r AND statement = :s",
            r=self.slice.run_id,
            s=statement,
        )
        return str(row["claim_id"])


class KeyedEmbeddings(HashEmbeddings):
    """Hash embeddings, except that chosen texts embed as another text: a question worded
    unlike any claim can stand for that claim's meaning (AT-43)."""

    def __init__(self) -> None:
        self.same: dict[str, str] = {}

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await super().embed([self.same.get(t, t) for t in texts])


@pytest.fixture
async def asker(thin_slice: Slice) -> AsyncIterator[AskClient]:
    assert thin_slice.ports is not None
    script = Script()

    def answerer(user: str) -> AnswererOutput:
        script.users.append(user)
        return script.answerer(user)

    models = ScriptedLLM(
        "anthropic", {"classifier": lambda _: script.classifier, "answerer": answerer}
    )
    embeddings = KeyedEmbeddings()
    app = create_app(env_file=None)
    app.state.container = Container(
        settings=thin_slice.settings,
        relational=thin_slice.store,
        graph=thin_slice.graph,
        vector=thin_slice.vector,
        embeddings=embeddings,
        llm={"anthropic": models},
        snapshots=thin_slice.ports.snapshots,
    )
    app.state.access = AccessConfig("a" * 12, "b" * 12, SECRET)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as client:
        yield AskClient(client, script, thin_slice, embeddings)


async def stored_answer(asker: AskClient, answer_id: str) -> dict[str, Any]:
    (row,) = await query_rows(
        asker.slice.store, "SELECT * FROM answer WHERE answer_id = :a", a=answer_id
    )
    return row


# --- a figure question: answer, trace, storage (AT-46) -------------------------------------


async def test_a_figure_question_is_answered_from_confirmed_facts_and_traced(
    asker: AskClient,
) -> None:
    """AT-46: the answer is stored with its trace: routes, removals, anchors, bundle and
    post-check actions."""
    asker.script.answerer = says(
        "In Halden Bay, 31.5% of adults with hypertension had it under control in 2024.",
        TRUE_STATEMENT,
    )
    body = await asker.ok("What share of people with hypertension have it under control?")
    (sentence,) = body["sentences"]
    assert sentence["kind"] == "fact"
    assert sentence["status_word"] == "Confirmed"
    assert sentence["refs"] == [await asker.claim_id(TRUE_STATEMENT)]
    assert body["question_type"] == "figure"
    assert body["turn"] == 1
    trace = body["trace"]
    assert set(trace["routes"]) == {"R1", "R2", "R3", "R4"}
    assert {"classification", "removed", "fused", "anchored", "bundle", "post_check"} <= set(trace)
    assert sentence["refs"][0] in trace["bundle"]
    row = await stored_answer(asker, body["answer_id"])
    assert row["trace"]["bundle"] == trace["bundle"]
    assert row["conversation_id"] == body["conversation_id"]
    assert row["cited_claim_ids"] == sentence["refs"]
    asker.client.cookies.set(COOKIE_NAME, issue_token("admin", SECRET))
    stored = await asker.client.get(f"/api/v1/admin/answers/{body['answer_id']}/trace")
    assert stored.json()["trace"]["routes"]["R1"]["status"] == "ok"


async def test_viewers_get_no_trace_and_the_admin_trace_needs_the_admin_role(
    asker: AskClient,
) -> None:
    body = await asker.ok(
        "What share of people with hypertension have it under control?", role="viewer"
    )
    assert body["trace"] is None
    response = await asker.client.get(f"/api/v1/admin/answers/{body['answer_id']}/trace")
    assert response.status_code == 403


async def test_the_trace_shows_reads_from_all_three_stores(asker: AskClient) -> None:
    """AT-11: questions of different types read the relational, vector and graph stores."""
    figure = await asker.ok("What share of people with hypertension have it under control?")
    asker.script.classifier = classified("relationship", ("S01",))
    asker.script.answerer = says(
        "The Halden Bay Health Office (HBHO) runs public health in Halden Bay.",
        NEW_GOV_STATEMENT,
        "S01",
    )
    relation = await asker.ok("Who runs public health in Halden Bay?")
    reads = [figure["trace"]["stores_read"], relation["trace"]["stores_read"]]
    assert all(r["postgres"] for r in reads)
    assert any(r["qdrant"] for r in reads)
    assert any(r["neo4j"] for r in reads)


# --- the graph (AT-10) --------------------------------------------------------------------------


async def test_a_relationship_question_is_answered_from_the_graph(asker: AskClient) -> None:
    """AT-10: answered from the graph; the graph route found the claim."""
    asker.script.classifier = classified("relationship", ("S01",))
    asker.script.answerer = says(
        "The Halden Bay Health Office (HBHO) runs public health in Halden Bay.",
        NEW_GOV_STATEMENT,
        "S01",
    )
    body = await asker.ok("Who runs public health in Halden Bay?")
    new_gov = await asker.claim_id(NEW_GOV_STATEMENT)
    assert body["graph_used"] is True
    assert [c for c, _ in body["trace"]["routes"]["R4"]["candidates"]] == [new_gov]
    assert body["sentences"][0]["refs"] == [new_gov]


async def test_with_the_graph_off_a_relationship_question_abstains(asker: AskClient) -> None:
    """AT-10 and R-88: switched off, no relation claim is read from elsewhere instead."""
    asker.script.classifier = classified("relationship", ("S01",))
    body = await asker.ok("Who runs public health in Halden Bay?", options={"graph": "off"})
    assert body["graph_used"] is False
    assert body["trace"]["bundle"] == []
    (sentence,) = body["sentences"]
    assert sentence["kind"] == "abstain"
    assert sentence["slot_id"] == "S01"
    assert "switched off" in sentence["text"]
    viewer = await asker.ask("Who runs public health in Halden Bay?", options={"graph": "off"})
    assert viewer.status_code == 403


async def test_a_change_question_shows_the_superseded_relation_as_superseded(
    asker: AskClient,
) -> None:
    """AT-10: superseded facts are shown as superseded."""
    asker.script.classifier = classified("change_over_time", ("S01",))
    asker.script.answerer = says(
        "Until March 2024 the Coastal District Office ran public health in Halden Bay.",
        OLD_GOV_STATEMENT,
        "S01",
    )
    body = await asker.ok("Who ran public health in Halden Bay before?")
    old_gov = await asker.claim_id(OLD_GOV_STATEMENT)
    assert old_gov in body["trace"]["bundle"]
    (sentence, *_) = body["sentences"]
    assert sentence["refs"] == [old_gov]
    assert sentence["status_word"] == "Replaced by newer information"


async def test_an_acronym_finds_the_organisation_by_its_full_name(asker: AskClient) -> None:
    """AT-42: "CDO" is never written in the evidence; its initials name the organisation."""
    asker.script.classifier = classified(
        "change_over_time", ("S01",), entity_mentions=[EntityMention(text="CDO", type=None)]
    )
    body = await asker.ok("What did the CDO run?")
    old_gov = await asker.claim_id(OLD_GOV_STATEMENT)
    assert old_gov in [c for c, _ in body["trace"]["routes"]["R2"]["candidates"]]


# --- recall and re-validation (AT-39, AT-40, AT-43, AT-44) --------------------------------------


async def test_a_refuted_claim_with_a_stale_index_entry_never_reaches_the_bundle(
    asker: AskClient,
) -> None:
    """AT-39: the vector index still calls it supported; Postgres has the final word."""
    (row,) = await query_rows(
        asker.slice.store,
        "SELECT claim_id, statement, quote FROM claim WHERE run_id = :r AND status = 'refuted'",
        r=asker.slice.run_id,
    )
    question = "Which claim did the checker reject?"
    vector = (await asker.embeddings.embed([question]))[0]
    collection = f"claim_index__{asker.embeddings.key}"
    await asker.slice.vector.upsert(
        collection,
        [
            VectorPoint(
                id=claim_point_id(row["claim_id"]),
                vector=vector,
                payload={
                    "claim_id": row["claim_id"],
                    "city_id": asker.slice.city_id,
                    "run_id": asker.slice.run_id,
                    "status": "supported",
                    "slot_id": "S04",
                },
            )
        ],
    )
    asker.script.classifier = classified("open", ())
    body = await asker.ok(question)
    trace = body["trace"]
    assert row["claim_id"] in [c for c, _ in trace["routes"]["R3"]["candidates"]]
    assert row["claim_id"] not in trace["bundle"]
    assert trace["removed"]["refuted"] >= 1


async def test_a_slot_s_best_claim_is_anchored_when_no_route_returns_it(
    asker: AskClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AT-40: with every route returning nothing, the slot's best claim is still in the
    bundle."""

    def nothing(route: str) -> Callable[..., Any]:
        async def found_nothing(*_: Any) -> RouteResult:
            return RouteResult(route, status="degraded", note="test")  # type: ignore[arg-type]

        return found_nothing

    for route in ("r1", "r2", "r3", "r4"):
        monkeypatch.setattr(pipeline, route, nothing(route.upper()))
    body = await asker.ok("zzz?")
    best = await asker.claim_id(TRUE_STATEMENT)
    assert best in body["trace"]["anchored"]
    assert best in body["trace"]["bundle"]


async def test_a_question_worded_unlike_the_claim_finds_it_by_meaning(asker: AskClient) -> None:
    """AT-43: the semantic route finds the claim; the keyword route does not."""
    question = "How many grown-ups keep their pressure in check?"
    true_id = await asker.claim_id(TRUE_STATEMENT)
    (row,) = await query_rows(
        asker.slice.store,
        "SELECT statement, quote, quote_translation FROM claim WHERE claim_id = :c",
        c=true_id,
    )
    asker.embeddings.same[question] = index_text(
        row["statement"], row["quote"], row["quote_translation"]
    )
    asker.script.classifier = classified("open", ())
    body = await asker.ok(question)
    routes = body["trace"]["routes"]
    assert routes["R3"]["candidates"][0][0] == true_id
    assert true_id not in [c for c, _ in routes["R2"]["candidates"]]
    assert true_id in body["trace"]["bundle"]


async def test_a_follow_up_uses_the_previous_turn_s_slots(asker: AskClient) -> None:
    """AT-44: "and nationally?" after a question on the control rate retrieves that slot."""
    first = await asker.ok("What share of people with hypertension have it under control?")
    asker.script.classifier = classified("out_of_scope", (), refers_to_previous=True)
    second = await asker.ok("And nationally?", conversation_id=first["conversation_id"])
    assert second["turn"] == 2
    assert second["trace"]["classification"]["merged_from_previous"] == ["S04"]
    assert await asker.claim_id(TRUE_STATEMENT) in second["trace"]["bundle"]
    assert "31.5%" not in asker.script.users[-1].split("<question>")[1]  # no previous answer text


async def test_a_conversation_of_another_city_is_refused(asker: AskClient) -> None:
    response = await asker.ask("And nationally?", conversation_id="conv_unknown")
    assert response.status_code == 404


# --- the post-check end to end (AT-15, AT-28, AT-45, AT-13) -------------------------------------


async def test_an_invented_office_holder_is_never_named(asker: AskClient) -> None:
    """AT-15 and AT-45: no evidence for who leads the office, so the system abstains."""
    asker.script.classifier = classified("relationship", ("S12",))
    asker.script.answerer = says(
        "Dr Mira Solberg leads the Halden Bay Health Office (HBHO).", NEW_GOV_STATEMENT, "S12"
    )
    body = await asker.ok("Who heads the Halden Bay Health Office?")
    assert not any("Solberg" in s["text"] for s in body["sentences"])
    assert any(s["kind"] == "abstain" for s in body["sentences"])
    assert body["trace"]["post_check"]["removed"] >= 1


async def test_a_number_not_in_the_evidence_becomes_an_abstention(asker: AskClient) -> None:
    """AT-28."""
    asker.script.answerer = says(
        "In Halden Bay, 45.0% of adults with hypertension had it under control.", TRUE_STATEMENT
    )
    body = await asker.ok("What share of people with hypertension have it under control?")
    assert not any("45.0" in s["text"] for s in body["sentences"])
    assert body["trace"]["post_check"]["removals"][0]["check"] == 2


async def test_a_wider_area_figure_stated_as_the_city_s_is_removed(asker: AskClient) -> None:
    """AT-13 for answers: a nearby place's figure never passes as the city's."""
    asker.script.answerer = says(
        "In Halden Bay, 27.0% of adults with hypertension had it controlled in 2023.",
        NEARBY_STATEMENT,
    )
    body = await asker.ok("What share of people with hypertension have it under control?")
    removals = body["trace"]["post_check"]["removals"]
    assert [r["check"] for r in removals] == [3]


async def test_an_out_of_scope_question_gets_one_abstention_and_no_search(asker: AskClient) -> None:
    asker.script.classifier = classified("out_of_scope", ())
    body = await asker.ok("What is the best football team?")
    (sentence,) = body["sentences"]
    assert (sentence["kind"], sentence["slot_id"]) == ("abstain", None)
    assert "routes" not in body["trace"]
    assert asker.script.users == []  # the answerer was never called


async def test_questions_are_limited_per_session(asker: AskClient) -> None:
    from app.api.limits import FailureLimiter

    asker.client._transport.app.state.ask_limiter = FailureLimiter(1, 60)  # type: ignore[attr-defined]
    await asker.ok("What share of people with hypertension have it under control?")
    again = await asker.ask(
        "What share of people with hypertension have it under control?", role="admin"
    )
    assert again.status_code == 429
