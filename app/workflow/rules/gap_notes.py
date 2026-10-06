"""Gap notes (LLD-2 §11.4, HD-05): fixed templates filled by code, never by a model.
The note says exactly what was searched and why nothing acceptable was found."""

from collections import Counter
from collections.abc import Sequence

from app.domain.geography import effective_level
from app.domain.models import Claim
from app.domain.vocab import CrawlOutcome, GeographyRelation, SlotStatus
from app.domain.wording import LEVEL_WORDS

OUTCOME_WORDS: dict[CrawlOutcome, str] = {
    CrawlOutcome.BLOCKED_ROBOTS: "robots.txt disallows",
    CrawlOutcome.BLOCKED_CONTENT_USAGE: "AI use not permitted",
    CrawlOutcome.BLOCKED_LOGIN_OR_PAYWALL: "login or paywall",
    CrawlOutcome.BLOCKED_PRIVATE_ADDRESS: "private address",
    CrawlOutcome.UNREACHABLE_NETWORK: "network error",
    CrawlOutcome.UNREACHABLE_SERVER_ERROR: "server error",
    CrawlOutcome.RATE_LIMITED: "rate limited",
}
TOP_REASONS = 3


def _count(n: int, one: str, many: str) -> str:
    """'1 source', '3 sources': gap notes are read by people (D4-3)."""
    return f"{n} {one if n == 1 else many}"


def _join(items: Sequence[str]) -> str:
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _top_reasons(outcomes: Sequence[CrawlOutcome]) -> str:
    counts = Counter(OUTCOME_WORDS[o] for o in outcomes if o in OUTCOME_WORDS)
    return ", ".join(f"{word} ({n})" for word, n in counts.most_common(TOP_REASONS))


def gap_note(
    status: SlotStatus,
    *,
    best: Claim | None = None,
    n_queries: int = 0,
    languages: Sequence[str] = (),
    n_sources: int = 0,
    crawl_outcomes: Sequence[CrawlOutcome] = (),
    unconfirmed: int = 0,
    unread: int = 0,
) -> str | None:
    """`languages`: display names of the search languages; `unconfirmed`: claims found
    but not confirmed (quote not found, refuted or insufficient); `unread`: sources the
    gate allowed that the run's budget stopped before they were read (BD-14)."""
    note: str | None
    if status is SlotStatus.ANSWERED:
        note = None
    elif status is SlotStatus.ANSWERED_WIDER_GEO:
        if best is None:
            raise ValueError("answered_wider_geo needs its best claim")
        labels = best.labels
        year = str(labels.reference_end.year) if labels.reference_end else "year not stated"
        fit = best.geography_fit
        # The level the figure counts as for the city, never its own label (BD-17)
        where = (
            "a nearby place"
            if fit is not None and fit.relation is GeographyRelation.NEARBY
            else LEVEL_WORDS[effective_level(best)]
        )
        note = (
            f"No city-level figure found. Best available is {where} "
            f"({labels.geography_name}, {year})."
        )
    elif status is SlotStatus.ANSWERED_NEGATIVE:
        note = (
            f"Searched {_count(n_queries, 'query', 'queries')} in "
            f"{_join(list(languages)) or 'no language'} and checked "
            f"{_count(n_sources, 'source', 'sources')}; nothing acceptable found for this question."
        )
    else:
        wanted = "blocked" if status is SlotStatus.BLOCKED else "unreachable"
        relevant = [
            o
            for o in crawl_outcomes
            if o.value.startswith(wanted)
            or (wanted == "unreachable" and o is CrawlOutcome.RATE_LIMITED)
        ]
        one = len(relevant) == 1
        if status is SlotStatus.BLOCKED:
            verb = "refuses automated access" if one else "refuse automated access"
        else:
            verb = "could not be reached"
        sources = _count(len(relevant), "candidate source", "candidate sources")
        note = f"{sources} {verb} ({_top_reasons(relevant)})."
    if unconfirmed and status is not SlotStatus.ANSWERED:
        found = "1 claim was" if unconfirmed == 1 else f"{unconfirmed} claims were"
        note = (note or "") + f" {found} found but could not be confirmed against their sources."
    if unread and status is not SlotStatus.ANSWERED:
        sources = "1 allowed source" if unread == 1 else f"{unread} allowed sources"
        note = (note or "") + f" The run's budget ran out before {sources} could be read."
    return note
