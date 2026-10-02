"""Chunking for Qdrant (LLD-1 §5.3). Prose: about `prose_tokens` tokens with about
`overlap_tokens` overlap, split on sentence boundaries. Tables: one chunk per table,
header row included; long tables split by rows with the header repeated.

Token counts are estimated as 4/3 of the word count; exact counts are not needed
for chunk sizing. Offsets always refer to the parsed text.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

TOKENS_PER_WORD = 4 / 3
_SENTENCE = re.compile(r"[^.!?\n]+(?:[.!?]+|\n|$)\s*")


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


def estimate_tokens(text: str) -> int:
    return round(len(text.split()) * TOKENS_PER_WORD)


def _sentences(text: str, offset: int) -> list[tuple[int, int]]:
    spans = []
    for m in _SENTENCE.finditer(text):
        if m.group().strip():
            spans.append((offset + m.start(), offset + m.end()))
    return spans


def _prose_chunks(text: str, start: int, end: int, params: ChunkParams) -> list[tuple[int, int]]:
    sentences = _sentences(text[start:end], start)
    chunks: list[tuple[int, int]] = []
    i = 0
    while i < len(sentences):
        j, tokens = i, 0
        while j < len(sentences) and (tokens == 0 or tokens < params.prose_tokens):
            tokens += estimate_tokens(text[sentences[j][0] : sentences[j][1]])
            j += 1
        chunks.append((sentences[i][0], sentences[j - 1][1]))
        if j >= len(sentences):
            break
        back, overlap = j, 0  # step back whole sentences to cover the overlap
        while back - 1 > i and overlap < params.overlap_tokens:
            back -= 1
            overlap += estimate_tokens(text[sentences[back][0] : sentences[back][1]])
        i = back if back > i else j
    return chunks


def _table_chunks(text: str, start: int, end: int, params: ChunkParams) -> list[str]:
    block = text[start:end].strip("\n")
    if estimate_tokens(block) <= params.table_max_tokens:
        return [block]
    lines = block.split("\n")
    header = (
        lines[:2]
        if len(lines) > 1 and set(lines[1].replace("|", "").strip()) <= set("-: ")
        else lines[:1]
    )
    pieces, current = [], list(header)
    for row in lines[len(header) :]:
        if estimate_tokens("\n".join([*current, row])) > params.table_max_tokens and len(
            current
        ) > len(header):
            pieces.append("\n".join(current))
            current = list(header)
        current.append(row)
    pieces.append("\n".join(current))
    return pieces


def chunk_text(text: str, tables: Sequence[tuple[int, int]], params: ChunkParams) -> list[Chunk]:
    """Split `text` into prose and table chunks in document order."""
    chunks: list[Chunk] = []
    cursor = 0
    for t_start, t_end in sorted(tables):
        for s, e in _prose_chunks(text, cursor, t_start, params):
            chunks.append(Chunk(len(chunks), s, e, text[s:e].strip(), False))
        for piece in _table_chunks(text, t_start, t_end, params):
            chunks.append(Chunk(len(chunks), t_start, t_end, piece, True))
        cursor = t_end
    for s, e in _prose_chunks(text, cursor, len(text), params):
        chunks.append(Chunk(len(chunks), s, e, text[s:e].strip(), False))
    return [c for c in chunks if c.text]
