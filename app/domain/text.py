"""Text normalisation shared by quote matching and the answer post-check (LLD-2 §4.1):
NFKC, typographic characters to ASCII, invisible characters removed, list bullets and
line-start list markers read as spaces (BD-47), line-break hyphenation joined, whitespace
collapsed, with each character's span in the original.
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
# List bullets are layout, not words: read as spaces, as are private-use characters,
# which PDFs set in symbol fonts for bullets (BD-47). The middle dot is kept: some
# journals print it as the decimal point.
_BULLETS = frozenset("•‣⁃∙■□▪▫●◦➢➔")
_LIST_MARKERS = frozenset("-*")  # a list item: at a line start, followed by a space


def _layout_space(ch: str) -> bool:
    return ch in _BULLETS or unicodedata.category(ch) == "Co"


def _drop_list_markers(chars: list[tuple[str, int, int]]) -> list[tuple[str, int, int]]:
    """A '-' or '*' that starts a line and is followed by a space is a list marker: a
    space. '-80' or a '-' inside a line is text."""
    out = list(chars)
    line_start = True
    for i, (ch, s, e) in enumerate(out):
        if ch in "\r\n":
            line_start = True
        elif ch in _HORIZONTAL_SPACE:
            continue
        else:
            if (
                line_start
                and ch in _LIST_MARKERS
                and i + 1 < len(out)
                and out[i + 1][0] in _HORIZONTAL_SPACE
            ):
                out[i] = (" ", s, e)
            line_start = False
    return out


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
        (" " if _layout_space(ch) else ch.translate(_TYPOGRAPHIC), s, e)
        for ch, s, e in _nfkc_chunks(text)
        if ch not in _REMOVED
    ]
    # 3b: bullets (above) and line-start list markers are layout: spaces (BD-47)
    chars = _drop_list_markers(chars)
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
