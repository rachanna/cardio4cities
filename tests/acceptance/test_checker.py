"""The independent checker (AT-07, AT-08), on an offline research run of slot S04."""

import pytest

from tests.support.thin_slice import (
    FAR_AWAY,
    MISSING_STATEMENT,
    PLANTED_STATEMENT,
    TRUE_STATEMENT,
    Slice,
    query_rows,
)

pytestmark = pytest.mark.db


async def test_checker_receives_only_the_restricted_slice(thin_slice: Slice) -> None:
    """AT-07: one claim, its labels and value, and the located passage; nothing else."""
    calls = [c for c in thin_slice.openai.calls if c.role == "checker"]
    assert len(calls) == 2  # the dropped claim is never checked
    for call in calls:
        assert FAR_AWAY not in call.user  # beyond the 600-character margin
        assert MISSING_STATEMENT not in call.user
        assert "SNIPPET-TEXT-NEVER-EVIDENCE" not in call.user
        assert "slot" not in call.user.lower()  # no slot question
        extractor_prompt = thin_slice.anthropic.calls[-1].system
        assert extractor_prompt[:200] not in call.user
    statements = [TRUE_STATEMENT in c.user for c in calls]
    assert sorted(statements) == [False, True]  # each call carries exactly its own claim
    planted_call = next(c for c in calls if PLANTED_STATEMENT in c.user)
    assert TRUE_STATEMENT not in planted_call.user


async def test_planted_unsupported_claim_is_refuted_and_never_a_fact(thin_slice: Slice) -> None:
    """AT-08: refuted with its reason recorded; absent from facts; the miss is logged."""
    s = thin_slice
    rows = await query_rows(
        s.store,
        "SELECT c.statement, c.status, v.label, v.rationale, v.verifier_family"
        " FROM claim c JOIN verdict v ON v.claim_id = c.claim_id WHERE c.run_id = :r",
        r=s.run_id,
    )
    planted = next(r for r in rows if r["statement"] == PLANTED_STATEMENT)
    assert planted["status"] == "refuted"
    assert planted["label"] == "refuted"
    assert "not that the city runs them" in planted["rationale"]
    assert planted["verifier_family"] == "openai"  # a different family from the extractor
    events = await s.store.runs.events_after(s.run_id, 0)
    dropped = [e["payload"] for e in events if e["type"] == "claim_dropped"]
    assert [(d["statement"], d["reason"]) for d in dropped] == [
        (MISSING_STATEMENT, "quote_not_found")
    ]
    written = [e["payload"]["claim_id"] for e in events if e["type"] == "fact_written"]
    assert len(written) == 1
