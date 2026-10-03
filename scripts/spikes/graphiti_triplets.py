"""Spike S-1: Graphiti triplets (BUILD_PLAN §2, LLD-1 §6.3). No paid calls.

Writes 20 fictional Halden Bay triplets to the local Neo4j through two paths and checks
the five S-1 criteria for each:

  A. `Graphiti.add_triplet` after saving our nodes (LLD-1 §6.3 primary design).
  B. Our own nodes and edges saved through Graphiti's model classes
     (`EntityNode.save`, `EntityEdge.save`), read back through Graphiti search.

Criteria: (1) our entity and edge UUIDs are kept; (2) no re-resolution: no model call
and no extra or merged node or edge; (3) edge attributes are returned by search;
(4) `invalid_at` set on an existing edge without deleting it; (5) model calls counted.

Graphiti's model is a counting stub that returns empty decisions: any call it receives
is a call the real system would pay for, and would let a model change the graph.
Embeddings are the local Sentence Transformers model (free). Telemetry is off.

    uv run poe spike graphiti_triplets
"""

# ruff: noqa: E501  (the relation table reads best one relation per line)
import asyncio
import os
import sys
import time
import typing
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

os.environ["GRAPHITI_TELEMETRY_ENABLED"] = "false"  # before graphiti_core is imported

from dotenv import load_dotenv
from graphiti_core import Graphiti
from graphiti_core.cross_encoder.client import CrossEncoderClient
from graphiti_core.edges import EntityEdge
from graphiti_core.embedder.client import EmbedderClient
from graphiti_core.llm_client.client import LLMClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.nodes import EntityNode
from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF
from graphiti_core.search.search_filters import (
    ComparisonOperator,
    DateFilter,
    SearchFilters,
)
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from app.container import build_container
from app.domain.ids import graph_uuid
from app.ports.embeddings import EmbeddingsPort
from app.settings import load_settings

RESULTS = Path(__file__).parent / "results" / "S-1-graphiti-triplets.md"

# --- stand-ins for Graphiti's model clients -----------------------------------------


def _empty(model: type[BaseModel]) -> dict[str, Any]:
    """A schema-valid 'decide nothing' answer: defaults, empty lists, None."""
    out: dict[str, Any] = {}
    for name, f in model.model_fields.items():
        if f.default is not PydanticUndefined:
            out[name] = f.default
        elif f.default_factory is not None:
            out[name] = f.default_factory()  # type: ignore[call-arg]
        else:
            origin = typing.get_origin(f.annotation)
            args = typing.get_args(f.annotation)
            if origin is list:
                out[name] = []
            elif type(None) in args:
                out[name] = None
            elif f.annotation is str:
                out[name] = ""
            elif f.annotation is bool:
                out[name] = False
            elif f.annotation in (int, float):
                out[name] = 0
            elif isinstance(f.annotation, type) and issubclass(f.annotation, BaseModel):
                out[name] = _empty(f.annotation)
            else:
                out[name] = None
    return out


class CountingModel(LLMClient):
    """Records every model call Graphiti makes; answers 'no change'."""

    def __init__(self) -> None:
        super().__init__(LLMConfig(api_key="none", model="counting-stub"))
        self.calls: list[str] = []

    async def generate_response(  # type: ignore[override]
        self, messages: Any, response_model: type[BaseModel] | None = None, **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append(kwargs.get("prompt_name") or "unnamed")
        return _empty(response_model) if response_model else {}

    async def _generate_response(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        raise AssertionError("not used")


class PortEmbedder(EmbedderClient):
    """Graphiti's embedder interface over our EmbeddingsPort, counting texts."""

    def __init__(self, port: EmbeddingsPort) -> None:
        self.port = port
        self.texts = 0

    async def create(self, input_data: Any) -> list[float]:
        texts = [input_data] if isinstance(input_data, str) else list(input_data)
        self.texts += len(texts)
        return (await self.port.embed([str(t) for t in texts]))[0]

    async def create_batch(self, input_data_list: list[str]) -> list[list[float]]:
        self.texts += len(input_data_list)
        return await self.port.embed(input_data_list)


class NoRerank(CrossEncoderClient):
    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        return [(p, 1.0) for p in passages]


# --- fictional data: 13 entities, 20 relations (LLD-1 §6.2 pairs only) -------------

ENTITIES = {
    "halden": ("Halden Bay", "Place"),
    "kestrel": ("Kestrel Point", "Place"),
    "directorate": ("Norvania Health Directorate", "Organization"),
    "coastal": ("Coastal District Office", "Organization"),
    "office": ("Halden Bay Health Office", "Organization"),
    "foundation": ("Heart Foundation of Norvania", "Organization"),
    "university": ("Halden Bay University", "Organization"),
    "marlow": ("Ines Marlow", "Person"),
    "vell": ("Tomas Vell", "Person"),
    "hearts": ("Healthy Hearts Halden Bay", "Programme"),
    "saltwatch": ("Salt Watch", "Programme"),
    "bread": ("Bread Salt Regulation", "Policy"),
    "htn": ("Hypertension control rate", "Indicator"),
}
D = datetime
RELATIONS: list[tuple[str, str, str, str, datetime | None]] = [
    ("coastal", "GOVERNS", "halden", "The Coastal District Office runs public health in Halden Bay.", D(2021, 1, 1, tzinfo=UTC)),
    ("office", "GOVERNS", "halden", "The Halden Bay Health Office runs public health in Halden Bay.", D(2024, 4, 1, tzinfo=UTC)),
    ("coastal", "REPLACED_BY", "office", "The Coastal District Office was replaced by the Halden Bay Health Office.", D(2024, 4, 1, tzinfo=UTC)),
    ("coastal", "PART_OF", "directorate", "The Coastal District Office is part of the Norvania Health Directorate.", None),
    ("kestrel", "PART_OF", "halden", "Kestrel Point lies within the Halden Bay metropolitan area.", None),
    ("marlow", "LEADS", "office", "Ines Marlow heads the Halden Bay Health Office.", D(2024, 4, 1, tzinfo=UTC)),
    ("vell", "LEADS", "office", "Tomas Vell heads the Halden Bay Health Office.", D(2025, 9, 1, tzinfo=UTC)),
    ("office", "RUNS", "hearts", "The Halden Bay Health Office runs Healthy Hearts Halden Bay.", D(2024, 6, 1, tzinfo=UTC)),
    ("foundation", "FUNDS", "hearts", "The Heart Foundation of Norvania funds Healthy Hearts Halden Bay.", D(2024, 6, 1, tzinfo=UTC)),
    ("hearts", "OPERATES_IN", "halden", "Healthy Hearts Halden Bay operates in Halden Bay clinics.", D(2024, 6, 1, tzinfo=UTC)),
    ("hearts", "OPERATES_IN", "kestrel", "Healthy Hearts Halden Bay operates in Kestrel Point.", D(2025, 1, 1, tzinfo=UTC)),
    ("office", "PARTNERS_WITH", "university", "The Halden Bay Health Office partners with Halden Bay University.", None),
    ("office", "PARTNERS_WITH", "foundation", "The Halden Bay Health Office partners with the Heart Foundation of Norvania.", None),
    ("directorate", "RUNS", "saltwatch", "The Norvania Health Directorate runs Salt Watch.", D(2023, 1, 1, tzinfo=UTC)),
    ("saltwatch", "OPERATES_IN", "halden", "Salt Watch operates in Halden Bay bakeries.", D(2023, 1, 1, tzinfo=UTC)),
    ("bread", "ISSUED_BY", "office", "The Bread Salt Regulation was issued by the Halden Bay Health Office.", D(2025, 7, 1, tzinfo=UTC)),
    ("bread", "APPLIES_TO", "halden", "The Bread Salt Regulation applies to Halden Bay.", D(2025, 7, 1, tzinfo=UTC)),
    ("htn", "MEASURED_IN", "halden", "The hypertension control rate was measured in Halden Bay.", D(2024, 1, 1, tzinfo=UTC)),
    ("htn", "MEASURED_IN", "kestrel", "The hypertension control rate was measured in Kestrel Point.", D(2023, 1, 1, tzinfo=UTC)),
    # a near-duplicate of the first relation from another source: must stay a separate edge
    ("coastal", "GOVERNS", "halden", "Public health in Halden Bay is the responsibility of the Coastal District Office.", D(2021, 1, 1, tzinfo=UTC)),
]  # fmt: skip


@dataclass
class Outcome:
    path: str
    model_calls: list[str] = field(default_factory=list)
    embedded_texts: int = 0
    seconds: float = 0.0
    uuids_kept: str = ""
    no_reresolution: str = ""
    attributes_in_search: str = ""
    invalidated_kept: str = ""
    notes: list[str] = field(default_factory=list)


def ok(flag: bool, detail: str) -> str:
    return f"{'PASS' if flag else 'FAIL'}: {detail}"


async def count(g: Graphiti, cypher: str, group: str) -> int:
    records, _, _ = await g.driver.execute_query(cypher, group_id=group)
    return int(records[0][0])


def nodes_for(group: str) -> dict[str, EntityNode]:
    return {
        key: EntityNode(uuid=graph_uuid(f"ent_{group}_{key}"), name=name, group_id=group,
                        labels=[kind], attributes={"entity_id": f"ent_{group}_{key}"})
        for key, (name, kind) in ENTITIES.items()
    }  # fmt: skip


def edges_for(group: str, nodes: dict[str, EntityNode]) -> list[EntityEdge]:
    edges = []
    for n, (s, rel, o, fact, valid) in enumerate(RELATIONS):
        claim_id = f"clm_{group}_{n:02d}"
        edges.append(EntityEdge(
            uuid=graph_uuid(claim_id), group_id=group, source_node_uuid=nodes[s].uuid,
            target_node_uuid=nodes[o].uuid, name=rel, fact=fact, episodes=[],
            created_at=datetime.now(UTC), valid_at=valid, invalid_at=None,
            attributes={"claim_ids": [claim_id], "source_ids": [f"src_{n % 5}"],
                        "status": "supported", "proxy_date": valid is None},
        ))  # fmt: skip
    return edges


async def check(g: Graphiti, group: str, nodes: dict[str, EntityNode],
                edges: list[EntityEdge], out: Outcome) -> None:  # fmt: skip
    expected = {e.uuid for e in edges}
    records, _, _ = await g.driver.execute_query(
        "MATCH ()-[e:RELATES_TO {group_id: $group_id}]->() RETURN e.uuid AS uuid, e.valid_at AS v",
        group_id=group,
    )
    stored = {r["uuid"] for r in records}
    node_count = await count(g, "MATCH (n:Entity {group_id: $group_id}) RETURN count(n)", group)
    out.uuids_kept = ok(stored == expected and node_count == len(nodes),
                        f"{len(stored & expected)}/{len(expected)} edge UUIDs ours, "
                        f"{len(stored - expected)} foreign; {node_count}/{len(nodes)} nodes")  # fmt: skip
    out.no_reresolution = ok(not out.model_calls and len(stored) == len(expected),
                             f"{len(out.model_calls)} model calls; {len(stored)} edges stored "
                             f"for {len(expected)} written")  # fmt: skip
    hits = (await g.search_("Who runs public health in Halden Bay?", config=EDGE_HYBRID_SEARCH_RRF,
                            group_ids=[group],
                            search_filter=SearchFilters(edge_types=["GOVERNS"]))).edges  # fmt: skip
    with_claims = [h for h in hits if h.attributes.get("claim_ids")]
    out.attributes_in_search = ok(bool(hits) and len(with_claims) == len(hits),
                                  f"{len(hits)} GOVERNS hits, {len(with_claims)} with claim_ids, "
                                  f"e.g. {hits[0].attributes if hits else None}")  # fmt: skip
    # Supersession by code: end-date the earlier LEADS edge, never delete it
    marlow = next(e for e in edges if e.name == "LEADS" and "Marlow" in e.fact)
    await g.driver.execute_query(
        "MATCH ()-[e:RELATES_TO {uuid: $uuid}]->() SET e.invalid_at = $at",
        uuid=marlow.uuid,
        at=datetime(2025, 9, 1, tzinfo=UTC),
    )
    still = await EntityEdge.get_by_uuid(g.driver, marlow.uuid)
    current = (await g.search_("Who heads the Halden Bay Health Office?",
                               config=EDGE_HYBRID_SEARCH_RRF, group_ids=[group],
                               search_filter=SearchFilters(edge_types=["LEADS"], invalid_at=[[
                                   DateFilter(comparison_operator=ComparisonOperator.is_null)]]),
                               )).edges  # fmt: skip
    every = (await g.search_("Who heads the Halden Bay Health Office?",
                             config=EDGE_HYBRID_SEARCH_RRF, group_ids=[group],
                             search_filter=SearchFilters(edge_types=["LEADS"]))).edges  # fmt: skip
    out.invalidated_kept = ok(
        still.invalid_at is not None and marlow.uuid not in {e.uuid for e in current}
        and marlow.uuid in {e.uuid for e in every},
        f"edge kept with invalid_at {still.invalid_at}; current-only search returns "
        f"{[e.fact for e in current]}; unfiltered returns {len(every)}",
    )  # fmt: skip


async def path_a(g: Graphiti, model: CountingModel, embedder: PortEmbedder) -> Outcome:
    group = f"spike_s1_a_{uuid.uuid4().hex[:8]}"
    out = Outcome("A: add_triplet after saving our nodes")
    nodes, start = nodes_for(group), time.monotonic()
    for node in nodes.values():
        await node.generate_name_embedding(embedder)
        await node.save(g.driver)
    edges = edges_for(group, nodes)
    for edge in edges:
        written = edge.model_copy(deep=True)
        result = await g.add_triplet(nodes_by_uuid(nodes, edge.source_node_uuid), written,
                                     nodes_by_uuid(nodes, edge.target_node_uuid))  # fmt: skip
        stored = result.edges[0]
        if stored.uuid != edge.uuid:
            out.notes.append(f"edge {edge.uuid[:8]} came back as {stored.uuid[:8]}")
        if stored.valid_at != edge.valid_at:
            out.notes.append(f"{edge.name}: valid_at {edge.valid_at} became {stored.valid_at}")
    out.seconds = time.monotonic() - start
    out.model_calls = list(model.calls)
    await check(g, group, nodes, edges, out)
    out.embedded_texts = embedder.texts
    await EntityNode.delete_by_group_id(g.driver, group)
    return out


def nodes_by_uuid(nodes: dict[str, EntityNode], node_uuid: str) -> EntityNode:
    return next(n for n in nodes.values() if n.uuid == node_uuid).model_copy(deep=True)


async def path_b(g: Graphiti, model: CountingModel, embedder: PortEmbedder) -> Outcome:
    group = f"spike_s1_b_{uuid.uuid4().hex[:8]}"
    out = Outcome("B: our nodes and edges saved through Graphiti's model classes")
    before_calls, before_texts = len(model.calls), embedder.texts
    nodes, start = nodes_for(group), time.monotonic()
    for node in nodes.values():
        await node.generate_name_embedding(embedder)
        await node.save(g.driver)
    edges = edges_for(group, nodes)
    for edge in edges:
        await edge.generate_embedding(embedder)
        await edge.save(g.driver)
    out.seconds = time.monotonic() - start
    out.model_calls = model.calls[before_calls:]
    await check(g, group, nodes, edges, out)
    out.embedded_texts = embedder.texts - before_texts
    await EntityNode.delete_by_group_id(g.driver, group)
    return out


async def main() -> int:
    load_dotenv(".env", override=False)
    settings = load_settings()
    container = build_container(settings)
    graph = settings.config.graph
    if container.embeddings is None:
        print("no embeddings adapter configured")
        return 1
    model, embedder = CountingModel(), PortEmbedder(container.embeddings)
    g = Graphiti(settings.secret(graph.uri_env), settings.secret(graph.user_env),
                 settings.secret(graph.password_env), llm_client=model,
                 embedder=embedder, cross_encoder=NoRerank())  # fmt: skip
    try:
        await g.build_indices_and_constraints()
        outcomes = []
        for run in (path_a, path_b):
            try:
                outcomes.append(await run(g, model, embedder))
            except Exception as exc:
                failed = Outcome(run.__name__)
                failed.notes.append(f"crashed: {type(exc).__name__}: {str(exc)[:300]}")
                outcomes.append(failed)
    finally:
        await g.close()  # type: ignore[no-untyped-call]
        await container.close()
    report(outcomes)
    return 0


def report(outcomes: list[Outcome]) -> None:
    lines = ["# Spike S-1: Graphiti triplets (graphiti-core 0.30.2, Neo4j 5)", "",
             f"{len(RELATIONS)} fictional relations, {len(ENTITIES)} entities, local embeddings "
             "(Sentence Transformers); Graphiti's model is a counting stub, so no paid call "
             "was made and every call shown is one the real system would make.", ""]  # fmt: skip
    for o in outcomes:
        calls: dict[str, int] = {}
        for name in o.model_calls:
            calls[name] = calls.get(name, 0) + 1
        lines += [f"## Path {o.path}", "",
                  f"- (1) our UUIDs kept: {o.uuids_kept}",
                  f"- (2) no re-resolution: {o.no_reresolution}",
                  f"- (3) attributes returned by search: {o.attributes_in_search}",
                  f"- (4) invalid_at without deletion: {o.invalidated_kept}",
                  f"- (5) model calls counted: {len(o.model_calls)} {calls or ''}; "
                  f"{o.embedded_texts} texts embedded; {o.seconds:.1f} s to write",
                  *[f"- note: {n}" for n in o.notes[:12]], ""]  # fmt: skip
    text = "\n".join(lines) + "\n"
    RESULTS.write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(asyncio.run(main()))
