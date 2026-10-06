"""Quote normalisation and matching (LLD-2 §4.1, R-56, AT-09).

Both sides go through the same normalisation; the match is then exact and
case-sensitive, with one exception: a quote that starts mid-sentence may differ from the
source in the case of its first letter only ("In 2022" for "in 2022", owner, BD-47). No
fuzzy matching under any circumstance: a quote that is not found drops its claim, and a
high drop rate means a parsing problem to fix.
"""

import re
from dataclasses import dataclass
from typing import Literal

from app.domain.params import QuoteParams
from app.domain.text import Normalised, normalise, normalise_text

__all__ = ["Normalised", "QuoteDrop", "QuoteMatch", "match_quote", "normalise", "normalise_text"]

DropReason = Literal["quote_length", "quote_not_found", "quote_not_unique", "value_not_in_quote"]


@dataclass(frozen=True)
class QuoteMatch:
    span_start: int  # offsets in the original parsed text
    span_end: int


@dataclass(frozen=True)
class QuoteDrop:
    reason: DropReason


def _stands_in(value: str, quote: str) -> bool:
    """`value` occurs in `quote` with no digit, or decimal part, run on at either end: "7%"
    is not in "17%" or "7.5%" (BD-33; code review RV-021). Still exact, never fuzzy."""
    pattern = rf"(?<!\d)(?<!\d[.,]){re.escape(value)}(?!\d)(?![.,]\d)"
    return re.search(pattern, quote) is not None


def match_quote(
    quote: str,
    parsed_text: str,
    params: QuoteParams,
    value_as_written: str | None = None,
    normalised: Normalised | None = None,
) -> QuoteMatch | QuoteDrop:
    """Locate `quote` in `parsed_text`. For statistic claims pass `value_as_written`:
    the value must occur inside the matched quote (WD-03). Quotes of `min_words_unique` to
    `min_words - 1` words must occur exactly once in the source (BD-08)."""
    nq = normalise_text(quote)
    words = len(nq.split(" ")) if nq else 0
    if not params.min_words_unique <= words <= params.max_words:
        return QuoteDrop("quote_length")
    # `normalised`: `normalise(parsed_text)` computed once by the caller for many quotes
    # (BD-27): each draft used to re-normalise its whole window on the event loop
    source = normalised if normalised is not None else normalise(parsed_text)
    at = source.text.find(nq)
    if at < 0 and nq[:1].isalpha():
        nq = nq[0].swapcase() + nq[1:]  # the first letter only (BD-47)
        at = source.text.find(nq)
    if at < 0:
        return QuoteDrop("quote_not_found")
    # A short quote (for example a table row) is accepted only when it occurs exactly once:
    # taking the first of several occurrences could anchor a value to the wrong row (BD-08).
    if words < params.min_words and source.text.find(nq, at + 1) >= 0:
        return QuoteDrop("quote_not_unique")
    if value_as_written is not None and not _stands_in(normalise_text(value_as_written), nq):
        return QuoteDrop("value_not_in_quote")
    return QuoteMatch(span_start=source.starts[at], span_end=source.ends[at + len(nq) - 1])
