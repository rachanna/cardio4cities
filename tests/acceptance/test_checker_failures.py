"""The checker's failure paths (BD-18; code review RV-015, RV-095, RV-004): with no checker
available nothing becomes a fact; the primary is tried exactly twice and the labelled
fallback answers next; and whatever writes a status, a claim becomes a fact only with a
supported verdict, and the facts view shows nothing else. Offline thin slice, fictional
Halden Bay."""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text

from app.adapters.postgres.relational import PostgresRelational
from app.domain.vocab import ClaimStatus, EventType
from app.workflow.claim_index import VerdictMismatchError, set_status
from tests.support.thin_slice import (
    PLANTED_STATEMENT,
    Slice,
    checker,
    extractor,
    planner,
    query_rows,
    run_slice,
)

pytestmark = [pytest.mark.db, pytest.mark.stores]


async def _events(store: PostgresRelational, run_id: str, kind: str) -> list[dict[str, Any]]:
    return [e for e in await store.runs.events_after(run_id, 0, 10_000) if e["type"] == kind]


async def test_with_no_checker_available_nothing_becomes_a_fact(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> None:
    """AT-08 failure path (RV-015): the primary and the fallback are both unavailable.
    Claims stay extracted, with no verdict, no fact event, no index point, no edge."""
    async with run_slice(relational, migrated, valid_env, openai_roles={}) as ran:
        statuses = await relational.research.claim_statuses(ran.run_id)
        assert statuses.get(ClaimStatus.EXTRACTED.value, 0) > 0
        assert not {"supported", "contested", "refuted", "insufficient"} & set(statuses)
        assert await _events(relational, ran.run_id, EventType.FACT_WRITTEN) == []
        verdicts = await query_rows(
            relational,
            "SELECT count(*) AS n FROM verdict JOIN claim USING (claim_id) WHERE run_id = :r",
            r=ran.run_id,
        )
        assert verdicts[0]["n"] == 0
        links = await query_rows(
            relational,
            "SELECT count(*) AS n FROM graph_link JOIN claim USING (claim_id) WHERE run_id = :r",
            r=ran.run_id,
        )
        assert links[0]["n"] == 0
        indexed = [p for name, ps in ran.vector.points.items() if "claim_index" in name for p in ps]
        assert indexed == []


async def test_the_primary_is_tried_twice_then_the_labelled_fallback_answers(
    relational: PostgresRelational, migrated: str, valid_env: dict[str, str]
) -> None:
    """R-82, LLD-2 §17 (RV-095): exactly two calls on the primary per claim, then one on
    the same-family fallback, whose verdicts are labelled `fallback_used`."""
    roles = {"planner": planner, "extractor": extractor, "checker": checker}
    async with run_slice(relational, migrated, valid_env, roles, openai_roles={}) as ran:
        verdicts = await query_rows(
            relational,
            "SELECT v.fallback_used, v.verifier_model FROM verdict v JOIN claim c"
            " USING (claim_id) WHERE c.run_id = :r",
            r=ran.run_id,
        )
        assert verdicts
        assert all(v["fallback_used"] for v in verdicts)
        assert {v["verifier_model"] for v in verdicts} == {"claude-opus-5-5"}
        primary = [c for c in ran.openai.calls if c.role == "checker"]
        fallback = [c for c in ran.anthropic.calls if c.role == "checker"]
        assert len(primary) == 2 * len(fallback) == 2 * len(verdicts)
        events = await _events(relational, ran.run_id, EventType.CLAIM_VERDICT)
        assert all(e["payload"]["fallback_used"] for e in events)


async def test_a_claim_without_a_supported_verdict_can_never_become_a_fact(
    thin_slice: Slice,
) -> None:
    """RV-004 guard (BD-18): the single status path refuses, and the facts view hides a
    claim whose status and verdict disagree, whatever wrote it."""
    store = thin_slice.store
    (planted,) = await query_rows(
        store,
        "SELECT claim_id FROM claim WHERE run_id = :r AND statement = :s",
        r=thin_slice.run_id,
        s=PLANTED_STATEMENT,
    )
    claim_id = planted["claim_id"]
    deps: Any = SimpleNamespace(relational=store)
    with pytest.raises(VerdictMismatchError):
        await set_status(deps, claim_id, ClaimStatus.SUPPORTED)
    (row,) = await query_rows(store, "SELECT status FROM claim WHERE claim_id = :c", c=claim_id)
    assert row["status"] == ClaimStatus.REFUTED.value

    async with store._engine.begin() as conn:  # a writer that bypassed the guard
        await conn.execute(
            text("UPDATE claim SET status = 'supported' WHERE claim_id = :c"), {"c": claim_id}
        )
    shown = await query_rows(
        store, "SELECT claim_id FROM v_city_facts WHERE run_id = :r", r=thin_slice.run_id
    )
    assert claim_id not in {s["claim_id"] for s in shown}
    assert shown  # the genuinely supported facts are still there
