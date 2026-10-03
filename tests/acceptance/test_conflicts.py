"""Conflicts and graph truth across the run (BD-19; code review RV-005, RV-030, RV-020):
two comparable figures that disagree are contested together even when different slots
found them; every decision is stored; a superseded relation keeps the date its edge ends
in Postgres. Offline thin slice, fictional Halden Bay."""

from decimal import Decimal

import pytest

from app.domain.models import Verdict
from app.domain.vocab import ClaimStatus, EventType, VerdictLabel
from app.workflow.claim_index import set_status
from app.workflow.conflicts import sweep_statistics
from app.workflow.runner import RunManager
from tests.support.thin_slice import TRUE_STATEMENT, Slice, query_rows

pytestmark = [pytest.mark.db, pytest.mark.stores]


async def test_figures_from_different_slots_that_disagree_are_contested_together(
    thin_slice: Slice,
) -> None:
    """RV-005: the comparison spans the whole run, not one slot's round. A second, comparable
    figure from another slot that disagrees makes both contested, with a pair and an event."""
    store, run_id = thin_slice.store, thin_slice.run_id
    assert thin_slice.ports is not None
    deps = await RunManager(thin_slice.ports, thin_slice.settings).build_deps(run_id)
    (row,) = await query_rows(
        store, "SELECT claim_id FROM claim WHERE run_id = :r AND statement = :s",
        r=run_id, s=TRUE_STATEMENT,
    )  # fmt: skip
    claim, statistic = await store.research.claim_with_statistic(row["claim_id"])
    assert statistic is not None
    comparable = claim.labels.model_copy(
        update={"threshold_code": "bp_140_90", "population_age_max": 69}
    )  # a recognised threshold and a full age band make a comparability key
    made = []
    for claim_id, slot_id, value in (
        ("clm_s04_cmp", "S04", "31.5"),
        ("clm_s03_cmp", "S03", "45.0"),
    ):
        figure = claim.model_copy(
            update={"claim_id": claim_id, "slot_id": slot_id, "labels": comparable}
        )
        await store.research.add_claim(
            figure,
            statistic.model_copy(
                update={
                    "claim_id": claim_id,
                    "value_as_written": f"{value}%",
                    "value_num": Decimal(value),
                }
            ),
        )
        await store.research.add_verdict(
            Verdict(
                claim_id=claim_id, label=VerdictLabel.SUPPORTED, rationale="Stated.",
                scope_verified=True, period_verified=True, verifier_model="test",
                verifier_family="test", prompt_version="test",
            )
        )  # fmt: skip
        await set_status(deps, claim_id, ClaimStatus.SUPPORTED)
        made.append(claim_id)
    first, second = made

    assert await sweep_statistics(deps, run_id) == 1

    statuses = await query_rows(
        store, "SELECT claim_id, status FROM claim WHERE claim_id IN (:a, :b)",
        a=first, b=second,
    )  # fmt: skip
    assert {r["status"] for r in statuses} == {ClaimStatus.CONTESTED.value}
    pairs = await query_rows(
        store, "SELECT claim_a, claim_b FROM contested_pair WHERE claim_a IN (:a, :b)",
        a=first, b=second,
    )  # fmt: skip
    assert len(pairs) == 1
    decisions = await query_rows(
        store, "SELECT claim_id, outcome FROM consistency WHERE claim_id IN (:a, :b)",
        a=first, b=second,
    )  # fmt: skip
    assert {d["outcome"] for d in decisions} == {"conflicts"}
    await sweep_statistics(deps, run_id)  # every round sweeps again: nothing is duplicated
    again = await query_rows(
        store, "SELECT count(*) AS n FROM contested_pair WHERE claim_a IN (:a, :b)",
        a=first, b=second,
    )  # fmt: skip
    assert again[0]["n"] == 1
    events = await store.runs.events_after(run_id, 0, 10_000)
    assert len([e for e in events if e["type"] == EventType.CONFLICT_FOUND]) == 1


async def test_every_supported_statistic_gets_a_stored_decision(thin_slice: Slice) -> None:
    """RV-005: the `consistency` table is written; a lone figure is novel."""
    rows = await query_rows(
        thin_slice.store,
        "SELECT c.claim_id, k.outcome FROM claim c JOIN statistic s USING (claim_id)"
        " LEFT JOIN consistency k USING (claim_id)"
        " WHERE c.run_id = :r AND c.status IN ('supported', 'contested')",
        r=thin_slice.run_id,
    )
    assert rows
    assert all(r["outcome"] is not None for r in rows)


async def test_a_superseded_relation_keeps_the_date_its_edge_ends(thin_slice: Slice) -> None:
    """RV-030: the end date lives in Postgres, so any slot or a resumed run writes the edge
    ended, never current."""
    rows = await query_rows(
        thin_slice.store,
        "SELECT r.superseded_on, g.invalidated_at FROM claim c JOIN relation r USING (claim_id)"
        " JOIN graph_link g USING (claim_id) WHERE c.run_id = :r AND c.status = 'superseded'",
        r=thin_slice.run_id,
    )
    assert len(rows) == 1
    assert rows[0]["superseded_on"].isoformat() == "2024-04-01"  # the successor's start
    assert rows[0]["invalidated_at"] is not None
