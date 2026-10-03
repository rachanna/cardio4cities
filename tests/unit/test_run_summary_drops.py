"""Run summary: dropped claims by reason, with geography_unresolved always shown (D2-4)."""

from app.workflow.nodes.brief_ready import drop_counts


def event(type_: str, reason: str | None = None) -> dict[str, object]:
    return {"type": type_, "payload": {"reason": reason} if reason else {}}


def test_drops_are_counted_by_reason() -> None:
    events = [
        event("claim_dropped", "quote_not_found"),
        event("claim_dropped", "geography_unresolved"),
        event("claim_dropped", "geography_unresolved"),
        event("claim_dropped", "geography_elsewhere"),
        event("claim_verdict"),
    ]
    assert drop_counts(events) == {
        "geography_unresolved": 2,
        "geography_elsewhere": 1,
        "quote_not_found": 1,
    }


def test_geography_unresolved_is_shown_even_when_zero() -> None:
    assert drop_counts([event("claim_dropped", "quote_not_found")]) == {
        "geography_unresolved": 0,
        "quote_not_found": 1,
    }
