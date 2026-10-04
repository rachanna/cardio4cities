"""Quote normalisation and matching (LLD-2 §4.1, R-56, AT-09).

Both sides go through the same normalisation; the match is then exact and
case-sensitive. No fuzzy matching under any circumstance: a quote that is not
found drops its claim, and a high drop rate means a parsing problem to fix.
"""

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

from app.domain.params import QuoteParams

_TYPOGRAPHIC = str.maketrans(
    {
        "‘": "'", "’": "'", "‚": "'", "‛": "'",
        "“": '"', "”": '"', "„": '"', "‟": '"',
        "–": "-", "—": "-",
        " ": " ",
    }
)  # fmt: skip
_REMOVED = frozenset("­​‌‍⁠﻿")  # soft hyphen, zero-width
_HORIZONTAL_SPACE = frozenset(" \t")

DropReason = Literal["quote_length", "quote_not_found", "quote_not_unique", "value_not_in_quote"]


@dataclass(frozen=True)
class Normalised:
    """Normalised text, with each character's span [start, end) in the original."""

    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]


@dataclass(frozen=True)
class QuoteMatch:
    span_start: int  # offsets in the original parsed text
    span_end: int


@dataclass(frozen=True)
class QuoteDrop:
    reason: DropReason


def _nfkc_chunks(text: str) -> list[tuple[str, int, int]]:
    """NFKC per base character with its combining marks, keeping original spans."""
    chunks: list[tuple[str, int, int]] = []
    i = 0
    while i < len(text):
        j = i + 1
        while j < len(text) and unicodedata.combining(text[j]):
            j += 1
        chunks.extend((ch, i, j) for ch in unicodedata.normalize("NFKC", text[i:j]))
        i = j
    return chunks


def normalise(text: str) -> Normalised:
    # 1-3: NFKC, typographic characters to ASCII, remove soft hyphens and zero-width characters
    chars = [
        (ch.translate(_TYPOGRAPHIC), s, e) for ch, s, e in _nfkc_chunks(text) if ch not in _REMOVED
    ]
    # 4: join line-break hyphenation: letter, '-', spaces, newline, spaces, lowercase letter
    joined: list[tuple[str, int, int]] = []
    i = 0
    while i < len(chars):
        ch = chars[i][0]
        if ch == "-" and joined and joined[-1][0].isalpha():
            j = i + 1
            while j < len(chars) and chars[j][0] in _HORIZONTAL_SPACE:
                j += 1
            if j < len(chars) and chars[j][0] in "\r\n":
                j += (
                    2
                    if chars[j][0] == "\r" and j + 1 < len(chars) and chars[j + 1][0] == "\n"
                    else 1
                )
                while j < len(chars) and chars[j][0] in _HORIZONTAL_SPACE:
                    j += 1
                if j < len(chars) and chars[j][0].isalpha() and chars[j][0].islower():
                    i = j
                    continue
        joined.append(chars[i])
        i += 1
    # 5: collapse whitespace runs to one space; trim
    out: list[tuple[str, int, int]] = []
    for ch, s, e in joined:
        if ch.isspace():
            if out and out[-1][0] == " ":
                out[-1] = (" ", out[-1][1], e)
            else:
                out.append((" ", s, e))
        else:
            out.append((ch, s, e))
    while out and out[0][0] == " ":
        out.pop(0)
    while out and out[-1][0] == " ":
        out.pop()
    return Normalised(
        text="".join(c for c, _, _ in out),
        starts=tuple(s for _, s, _ in out),
        ends=tuple(e for _, _, e in out),
    )


def normalise_text(text: str) -> str:
    return normalise(text).text


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
    if at < 0:
        return QuoteDrop("quote_not_found")
    # A short quote (for example a table row) is accepted only when it occurs exactly once:
    # taking the first of several occurrences could anchor a value to the wrong row (BD-08).
    if words < params.min_words and source.text.find(nq, at + 1) >= 0:
        return QuoteDrop("quote_not_unique")
    if value_as_written is not None and not _stands_in(normalise_text(value_as_written), nq):
        return QuoteDrop("value_not_in_quote")
    return QuoteMatch(span_start=source.starts[at], span_end=source.ends[at + len(nq) - 1])
