"""Text normalisation shared by quote matching and the answer post-check (LLD-2 §4.1):
NFKC, typographic characters to ASCII, invisible characters removed, line-break
hyphenation joined, whitespace collapsed, with each character's span in the original.
Pure (moved from `workflow/rules/quotes.py` for `app/query`, BD-38)."""

import unicodedata
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Normalised:
    """Normalised text, with each character's span [start, end) in the original."""

    text: str
    starts: tuple[int, ...]
    ends: tuple[int, ...]


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
