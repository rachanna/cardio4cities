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

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.domain.models import LabelKind, Labels
from app.domain.params import QuoteParams
from app.domain.vocab import PeriodType, Sex
from app.workflow.rules.quotes import Normalised, QuoteDrop, match_quote, normalise_text

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
    normalised: Normalised | None = None,
) -> LabelEvidence:
    """`window` is the text the extractor read; it starts at `window_start` in the
    document. A period quote must also contain each year of the labelled period."""
    spans: dict[LabelKind, tuple[int, int]] = {}
    cleared: set[LabelKind] = set()
    for kind, quote in quotes.items():
        if not quote or not quote.strip():
            continue
        found = match_quote(quote, window, params, normalised=normalised)
        located = not isinstance(found, QuoteDrop)
        if located and kind == "period":
            stated = normalise_text(window[found.span_start : found.span_end])  # type: ignore[union-attr]
            located = all(year in stated for year in _years(labels))
        if located:
            spans[kind] = (window_start + found.span_start, window_start + found.span_end)  # type: ignore[union-attr]
        elif kind in CLEARABLE:
            cleared.add(kind)
    return LabelEvidence(spans=spans, cleared=frozenset(cleared))


_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
_SPAN_MARKS = "-/\u2013"  # hyphen, slash, en dash


def _number_forms(token: str) -> set[str]:
    """A number as a source may write it: "7.0" or "7,0"; "1204" or "1,204"."""
    forms = {token, token.replace(".", ","), token.replace(",", ".")}
    if token.isdigit() and len(token) > 3:
        head, tail = token[:-3], token[-3:]
        forms |= {f"{head}{sep}{tail}" for sep in (",", ".", " ")}
    return forms


def states_number(texts: Sequence[str], token: str) -> bool:
    """`token` stands as a whole number in one of the texts: "30" is in "aged 30-79", not
    in "130" or "30.5"."""
    for form in _number_forms(token):
        pattern = re.compile(rf"(?<![\d.,]){re.escape(form)}(?![\d]|[.,]\d)")
        if any(pattern.search(t) for t in texts):
            return True
    return False


def _states_year(texts: Sequence[str], year: str) -> bool:
    """A year in full, or as the short end of a span: "2024" in "2023-24" or "2023/24"."""
    short = re.compile(rf"\d{{4}}\s*[{_SPAN_MARKS}]\s*{year[2:]}(?!\d)")
    return states_number(texts, year) or any(short.search(t) for t in texts)


@dataclass(frozen=True)
class Located:
    labels: Labels
    cleared: tuple[str, ...]  # label names cleared because the evidence does not state them


def keep_located(labels: Labels, evidence: Sequence[str]) -> Located:
    """Labels whose numbers code can find in `evidence` (the located quote and label
    passages) are kept; the others are cleared, never guessed (owner, BD-22; R-89).
    Checked: the age band, the sample size, the numbers in the case definition (which set
    its threshold) and the years of a stated period."""
    texts = [normalise_text(t) for t in evidence]
    update: dict[str, object] = {}
    cleared: list[str] = []
    ages = [a for a in (labels.population_age_min, labels.population_age_max) if a is not None]
    if ages and not all(states_number(texts, str(a)) for a in ages):
        update |= {"population_age_min": None, "population_age_max": None}
        cleared.append("age_band")
    if labels.sample_size is not None and not states_number(texts, str(labels.sample_size)):
        update["sample_size"] = None
        cleared.append("sample_size")
    if labels.case_definition:
        numbers = _NUMBER.findall(labels.case_definition)
        if numbers and not all(states_number(texts, n) for n in numbers):
            update |= {"case_definition": None, "threshold_code": None}
            cleared.append("case_definition")
    if labels.period_type is not PeriodType.PUBLICATION_DATE_PROXY:
        years = sorted(_years(labels))
        if years and not all(_states_year(texts, y) for y in years):
            update |= {
                "reference_start": None,
                "reference_end": None,
                "reference_precision": None,
                "period_type": PeriodType.PUBLICATION_DATE_PROXY,
            }
            cleared.append("period")
    return Located(labels.model_copy(update=update) if update else labels, tuple(cleared))


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
            "population_subgroup": None,
        }
    return labels.model_copy(update=update) if update else labels
