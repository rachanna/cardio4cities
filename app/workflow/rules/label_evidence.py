"""Label evidence (BD-10). A label is often stated outside the quote: the survey period in
the methods, the area in a table title. The extractor may copy the words that state it
(a label quote); code locates each one exactly, with the same rules as claim quotes
(R-56), and the checker then sees those passages too (R-38: every passage it sees is
located by code).

A label quote that cannot be located means the label is not established: the period
and the population labels are then cleared (never guessed, R-89), so the figure carries
its "not stated" flags instead. The geography label is required, so it is never cleared;
the checker decides whether the passages establish it.
"""

from collections.abc import Mapping
from dataclasses import dataclass

from app.domain.models import LabelKind, Labels
from app.domain.params import QuoteParams
from app.domain.vocab import PeriodType, Sex
from app.workflow.rules.quotes import QuoteDrop, match_quote, normalise_text

CLEARABLE: frozenset[LabelKind] = frozenset({"period", "population"})


@dataclass(frozen=True)
class LabelEvidence:
    spans: dict[LabelKind, tuple[int, int]]  # document offsets
    cleared: frozenset[LabelKind]


def _years(labels: Labels) -> set[str]:
    return {str(d.year) for d in (labels.reference_start, labels.reference_end) if d}


def locate_label_quotes(
    quotes: Mapping[LabelKind, str | None],
    window: str,
    window_start: int,
    labels: Labels,
    params: QuoteParams,
) -> LabelEvidence:
    """`window` is the text the extractor read; it starts at `window_start` in the
    document. A period quote must also contain each year of the labelled period."""
    spans: dict[LabelKind, tuple[int, int]] = {}
    cleared: set[LabelKind] = set()
    for kind, quote in quotes.items():
        if not quote or not quote.strip():
            continue
        found = match_quote(quote, window, params)
        located = not isinstance(found, QuoteDrop)
        if located and kind == "period":
            stated = normalise_text(window[found.span_start : found.span_end])  # type: ignore[union-attr]
            located = all(year in stated for year in _years(labels))
        if located:
            spans[kind] = (window_start + found.span_start, window_start + found.span_end)  # type: ignore[union-attr]
        elif kind in CLEARABLE:
            cleared.add(kind)
    return LabelEvidence(spans=spans, cleared=frozenset(cleared))


def clear_labels(labels: Labels, cleared: frozenset[LabelKind]) -> Labels:
    update: dict[str, object] = {}
    if "period" in cleared:
        update |= {
            "reference_start": None,
            "reference_end": None,
            "reference_precision": None,
            "period_type": PeriodType.PUBLICATION_DATE_PROXY,
        }
    if "population" in cleared:
        update |= {
            "population_age_min": None,
            "population_age_max": None,
            "population_sex": Sex.NOT_STATED,
            "population_group": None,
        }
    return labels.model_copy(update=update) if update else labels
