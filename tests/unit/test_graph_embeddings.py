"""Graph writes embed through the run's port (BD-36; code review RV-091): both names and
the fact in one call, reserved first; each programme-status update reserves its own."""

from types import SimpleNamespace
from typing import Any

from app.ports.graph import GraphEdge, GraphEntity
from app.workflow.graph_writes import _embedded
from tests.support.workflow_fakes import HashEmbeddings


class Recorder:
    def __init__(self) -> None:
        self.log: list[str] = []
        self.model = HashEmbeddings()

    async def reserve(self, kind: str) -> None:
        self.log.append(f"reserve:{kind}")

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.log.append(f"embed:{len(texts)}")
        return await self.model.embed(texts)


def node(name: str) -> GraphEntity:
    return GraphEntity(uuid=name, group_id="city_hb", entity_type="Place", name=name, attributes={})


async def test_names_and_fact_are_embedded_in_one_reserved_call() -> None:
    r = Recorder()
    d: Any = SimpleNamespace(ledger=r, embeddings=r)
    fact = GraphEdge(
        uuid="e1", group_id="city_hb", name="GOVERNS", fact="The office runs\npublic health.",
        valid_at=None, invalid_at=None, attributes={},
    )  # fmt: skip

    subject, edge, obj = await _embedded(
        d, node("Halden Bay Health Office"), fact, node("Halden Bay")
    )

    assert r.log == ["reserve:indexing", "embed:3"]
    expected = await r.model.embed(
        ["Halden Bay Health Office", "Halden Bay", "The office runs public health."]
    )
    assert (subject.name_embedding, obj.name_embedding, edge.fact_embedding) == tuple(expected)
