"""AT-03: the compiled workflow renders, and its conditional edges route the crawl
decision, the verdict and the sufficiency loop (R-02, R-37; code review RV-062). That state
can be read between nodes is checked on a checkpointed run
(`checkpointed/test_resume.py`)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest

from app.workflow.graph import build_graph

SLOT = "slot_subgraph:"


def conditional_edges() -> set[tuple[str, str]]:
    graph = build_graph().get_graph(xray=1)
    return {(e.source, e.target) for e in graph.edges if e.conditional}


def test_the_workflow_renders_with_its_slot_subgraph() -> None:
    """AT-03: Mermaid text for the main graph with the slot subgraph drawn inside it."""
    mermaid = build_graph().get_graph(xray=1).draw_mermaid()

    for node in ("resolve_city", "wave0", "plan_slots", "coverage", "brief_ready"):
        assert f"\t{node}({node})" in mermaid
    assert "subgraph slot_subgraph" in mermaid
    for node in ("search", "crawl_gate", "fetch_parse", "extract", "match_quotes", "verify"):
        assert f"({node})" in mermaid
    assert "-.->" in mermaid  # conditional edges are drawn dotted


def test_the_crawl_decision_routes_to_fetching_or_to_a_recorded_gap() -> None:
    """AT-03: the gate's decision has consequences: allowed pages are fetched, refused
    ones become a gap (R-02, non-negotiable 3)."""
    assert {
        (f"{SLOT}crawl_gate", f"{SLOT}fetch_parse"),
        (f"{SLOT}crawl_gate", f"{SLOT}record_gate_gap"),
    } <= conditional_edges()


def test_the_verdict_routes_supported_claims_on_and_others_to_unsupported() -> None:
    """AT-03: verdict routing (non-negotiable 4)."""
    assert {
        (f"{SLOT}verify", f"{SLOT}consistency"),
        (f"{SLOT}verify", f"{SLOT}record_unsupported"),
    } <= conditional_edges()


def test_the_sufficiency_loop_re_plans_or_moves_on() -> None:
    """AT-03: coverage sends insufficient slots back to planning, or the run on to
    analytics; planning fans slots out to the subgraph."""
    assert {
        ("coverage", "plan_slots"),
        ("coverage", "analytics"),
        ("plan_slots", f"{SLOT}search"),
    } <= conditional_edges()


def test_the_diagram_endpoint_serves_the_compiled_graphs(monkeypatch: pytest.MonkeyPatch) -> None:
    """AT-03 for the demo (DS-2): the API returns Mermaid text generated from the code."""
    from fastapi.testclient import TestClient

    from app.api.auth import COOKIE_NAME, AccessConfig, issue_token
    from app.main import create_app

    app = create_app(env_file=None)
    app.router.lifespan_context = _no_lifespan
    app.state.access = AccessConfig("a" * 12, "b" * 12, "diagram-test-signing-key")
    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/api/v1/workflow/diagram").status_code == 401
        client.cookies.set(COOKIE_NAME, issue_token("viewer", "diagram-test-signing-key"))
        body = client.get("/api/v1/workflow/diagram").json()
    assert "subgraph slot_subgraph" in body["main"]
    assert "crawl_gate" in body["slot"]
    assert "-.->" in body["slot"]


@asynccontextmanager
async def _no_lifespan(_: object) -> AsyncIterator[None]:
    yield
