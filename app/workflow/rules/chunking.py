"""Chunking for Qdrant (LLD-1 §5.3). Prose: about `prose_tokens` tokens with about
`overlap_tokens` overlap, split on sentence boundaries. Tables: one chunk per table,
header row included; long tables split by rows with the header repeated.

Token counts are estimated from characters, with factors by script (BD-29): about 4
characters a token for ASCII, 2 for other alphabets, 1 for scripts written without
spaces (Chinese, Japanese, Korean, Thai, Burmese, Khmer). Counting words underestimated
numbers, tables and non-Latin pages by 1.5 to 4 times, and a page with no spaces became
one chunk. Offsets always refer to the parsed text.
"""

import bisect
import itertools
import re
from collections.abc import Sequence
from dataclasses import dataclass

ASCII_CHARS_PER_TOKEN = 4.0
OTHER_CHARS_PER_TOKEN = 2.0
WIDE_CHARS_PER_TOKEN = 1.0
# Scripts written without spaces between words (code point ranges)
_WIDE = re.compile(
    "[\u0e00-\u0e7f\u1000-\u109f\u1780-\u17ff\u2e80-\u9fff\uac00-\ud7af\uf900-\ufaff]"
)
# Sentence ends, the full stops of scripts without spaces included
_SENTENCE = re.compile("[^.!?\n\u3002\uff01\uff1f]+(?:[.!?\u3002\uff01\uff1f]+|\n|$)\\s*")


@dataclass(frozen=True)
class ChunkParams:
    prose_tokens: int  # chunk.prose_tokens [tunable]
    overlap_tokens: int  # chunk.overlap_tokens [tunable]
    table_max_tokens: int  # chunk.table_max_tokens [tunable]


@dataclass(frozen=True)
class Chunk:
    index: int
    start: int
    end: int
    text: str
    is_table: bool


def _char_cost(char: str) -> float:
    if ord(char) < 128:
        return 1 / ASCII_CHARS_PER_TOKEN
    if _WIDE.match(char):
        return 1 / WIDE_CHARS_PER_TOKEN
    return 1 / OTHER_CHARS_PER_TOKEN


def estimate_tokens(text: str) -> int:
    return round(sum(_char_cost(c) for c in text))


def _prefix_costs(text: str) -> list[float]:
    """cost[i] is the estimated tokens of text[:i]."""
    return [0.0, *itertools.accumulate(_char_cost(c) for c in text)]


def _cut_back(text: str, start: int, end: int) -> int:
    """`end`, moved back to just after the last whitespace in the second half of
    [start, end), so a cut falls between words; scripts without spaces cut anywhere."""
    for i in range(end - 1, start + (end - start) // 2, -1):
        if text[i].isspace():
            return i + 1
    return end


def _sentences(text: str, offset: int, max_tokens: float) -> list[tuple[int, int]]:
    """Sentence spans; one longer than `max_tokens` (a page with no full stops, a script
    without spaces) is cut by characters (BD-29)."""
    spans = []
    for m in _SENTENCE.finditer(text):
        if not m.group().strip():
            continue
        start, end = m.start(), m.end()
        if estimate_tokens(m.group()) <= max_tokens:
            spans.append((offset + start, offset + end))
            continue
        cost = _prefix_costs(text[start:end])
        piece = 0
        while piece < end - start:
            stop = bisect.bisect_left(cost, cost[piece] + max_tokens, lo=piece + 1)
            stop = min(stop, end - start)
            if stop < end - start:
                stop = _cut_back(text, start + piece, start + stop) - start
            spans.append((offset + start + piece, offset + start + stop))
            piece = stop
    return spans


def _trimmed(text: str, start: int, end: int) -> tuple[int, int]:
    """The span without the whitespace its chunk text strips (code review RV-077)."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _prose_chunks(text: str, start: int, end: int, params: ChunkParams) -> list[tuple[int, int]]:
    sentences = _sentences(text[start:end], start, params.prose_tokens)
    chunks: list[tuple[int, int]] = []
    i = 0
    while i < len(sentences):
        j, tokens = i, 0
        while j < len(sentences) and (tokens == 0 or tokens < params.prose_tokens):
            tokens += estimate_tokens(text[sentences[j][0] : sentences[j][1]])
            j += 1
        chunks.append(_trimmed(text, sentences[i][0], sentences[j - 1][1]))
        if j >= len(sentences):
            break
        back, overlap = j, 0  # step back whole sentences to cover the overlap
        while back - 1 > i and overlap < params.overlap_tokens:
            back -= 1
            overlap += estimate_tokens(text[sentences[back][0] : sentences[back][1]])
        i = back if back > i else j
    return chunks


def _table_chunks(
    text: str, start: int, end: int, params: ChunkParams
) -> list[tuple[str, int, int]]:
    """(text, start, end) per piece. A piece's span covers its own rows, not the whole
    table (code review RV-077); its text repeats the header."""
    block_start, block_end = _trimmed(text, start, end)
    block = text[block_start:block_end]
    if estimate_tokens(block) <= params.table_max_tokens:
        return [(block, block_start, block_end)]
    lines = block.split("\n")
    offsets: list[tuple[int, int]] = []
    at = block_start
    for line in lines:
        offsets.append((at, at + len(line)))
        at += len(line) + 1
    separator = len(lines) > 1 and set(lines[1].replace("|", "").strip()) <= set("-: ")
    header = lines[: 2 if separator else 1]
    pieces: list[tuple[str, int, int]] = []
    rows: list[int] = []
    for n in range(len(header), len(lines)):
        candidate = "\n".join([*header, *(lines[r] for r in [*rows, n])])
        if estimate_tokens(candidate) > params.table_max_tokens and rows:
            pieces.append(_piece(header, lines, offsets, rows))
            rows = []
        rows.append(n)
    if rows:
        pieces.append(_piece(header, lines, offsets, rows))
    return pieces


def _piece(
    header: list[str], lines: list[str], offsets: list[tuple[int, int]], rows: list[int]
) -> tuple[str, int, int]:
    piece = "\n".join([*header, *(lines[r] for r in rows)])
    return piece, offsets[rows[0]][0], offsets[rows[-1]][1]


def chunk_text(text: str, tables: Sequence[tuple[int, int]], params: ChunkParams) -> list[Chunk]:
    """Split `text` into prose and table chunks in document order."""
    chunks: list[Chunk] = []
    cursor = 0
    for t_start, t_end in sorted(tables):
        for s, e in _prose_chunks(text, cursor, t_start, params):
            chunks.append(Chunk(len(chunks), s, e, text[s:e].strip(), False))
        for piece, p_start, p_end in _table_chunks(text, t_start, t_end, params):
            chunks.append(Chunk(len(chunks), p_start, p_end, piece, True))
        cursor = t_end
    for s, e in _prose_chunks(text, cursor, len(text), params):
        chunks.append(Chunk(len(chunks), s, e, text[s:e].strip(), False))
    return [c for c in chunks if c.text]


def pick_windows(
    text: str, spans: Sequence[tuple[int, int]], terms: Sequence[str], cap: int
) -> list[tuple[int, int, int]]:
    """(number, start, end) of at most `cap` windows: those with the most whole-word
    hits for `terms` (the city's names and the slot's words), earlier ones first on a
    tie, returned in document order (owner, BD-29). `number` counts from 1 over all."""
    words = [t.casefold() for t in terms if t and t.strip()]
    patterns = [re.compile(rf"(?<!\w){re.escape(w)}(?!\w)") for w in words]

    def hits(span: tuple[int, int]) -> int:
        window = text[span[0] : span[1]].casefold()
        return sum(len(p.findall(window)) for p in patterns)

    numbered = list(enumerate(spans, 1))
    best = sorted(numbered, key=lambda item: (-hits(item[1]), item[0]))[: max(cap, 0)]
    return [(n, start, end) for n, (start, end) in sorted(best)]


def windows(text: str, window_tokens: int, overlap_tokens: int) -> list[tuple[int, int]]:
    """Extraction windows (LLD-3 §4.1): spans of about `window_tokens` estimated tokens
    with about `overlap_tokens` overlap, cut between words where the script has spaces
    (BD-29). Offsets refer to `text`."""
    first = next((i for i, c in enumerate(text) if not c.isspace()), None)
    if first is None:
        return []
    cost, n = _prefix_costs(text), len(text)
    spans: list[tuple[int, int]] = []
    start = first
    while start < n:
        stop = min(bisect.bisect_left(cost, cost[start] + window_tokens, lo=start + 1), n)
        if stop < n:
            stop = _cut_back(text, start, stop)
        spans.append(_trimmed(text, start, stop))
        if stop >= n or not text[stop:].strip():
            break
        back = bisect.bisect_left(cost, cost[stop] - overlap_tokens, lo=start + 1)
        back = min(max(back, start + 1), stop)
        while back < stop and not text[back - 1].isspace() and not _WIDE.match(text[back]):
            back += 1  # start the next window at a word, not inside one
        start = back
        while start < n and text[start].isspace():
            start += 1
    return spans
