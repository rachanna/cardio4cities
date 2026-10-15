"""R4 shaped by the question (E-07, BD-57): ranking reorders the in-scope edges, it never
drops one."""

from app.ports.graph import GraphEdge, GraphEdgeHit, GraphEntity
from app.query.routes.graph import ranked_first

OFFICE = GraphEntity(
    uuid="n1", group_id="c", entity_type="Organization", name="Health Office", attributes={}
)
CITY = GraphEntity(uuid="n2", group_id="c", entity_type="Place", name="Halden Bay", attributes={})


def hit(uuid: str) -> GraphEdgeHit:
    edge = GraphEdge(
        uuid=uuid, group_id="c", name="RUNS", fact=f"fact {uuid}",
        valid_at=None, invalid_at=None, attributes={},
    )  # fmt: skip
    return GraphEdgeHit(edge=edge, subject=OFFICE, object=CITY)


def test_ranked_edges_come_first_and_unranked_ones_follow_in_structural_order() -> None:
    structural = [hit("e1"), hit("e2"), hit("e3"), hit("e4")]
    ranked = [hit("e3"), hit("e1")]  # Graphiti's similarity cut-off left e2 and e4 out

    assert [h.edge.uuid for h in ranked_first(ranked, structural)] == ["e3", "e1", "e2", "e4"]


def test_no_ranking_keeps_the_structural_order() -> None:
    structural = [hit("e1"), hit("e2")]
    assert [h.edge.uuid for h in ranked_first([], structural)] == ["e1", "e2"]
