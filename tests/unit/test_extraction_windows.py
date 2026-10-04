"""Bounded extraction (BD-29; code review RV-044, RV-054, RV-060, RV-077, RV-100): tokens
estimated by characters with script factors, windows and chunks that never run past their
size, the most relevant windows chosen per (slot, source), late windows not started, and
PDF tables without empty columns. Fictional text only."""

from itertools import pairwise
from types import SimpleNamespace
from typing import Any

from app.adapters.parse.documents import _pipe_table
from app.workflow.nodes.extract import Window, _extract_window
from app.workflow.rules.chunking import (
    ChunkParams,
    chunk_text,
    estimate_tokens,
    pick_windows,
    windows,
)

PARAMS = ChunkParams(prose_tokens=100, overlap_tokens=10, table_max_tokens=60)


def test_tokens_are_estimated_by_characters_with_script_factors() -> None:
    """RV-044: word counts underestimated numbers and non-Latin text by 1.5 to 4 times."""
    assert estimate_tokens("a" * 400) == 100  # ASCII: about 4 characters a token
    assert estimate_tokens("\u0430" * 400) == 200  # Cyrillic: about 2
    assert estimate_tokens("\u6e2f" * 400) == 400  # Chinese: about 1, no spaces
    assert estimate_tokens("31.2% 27.4% 19.0% 22.6%") >= 5  # numbers are not one token each


def test_a_window_never_runs_past_its_size_even_without_spaces() -> None:
    """A page with no spaces used to be one window and one chunk of any length."""
    text = "\u6e2f" * 5000
    spans = windows(text, window_tokens=1000, overlap_tokens=100)
    assert len(spans) >= 5
    assert all(estimate_tokens(text[a:b]) <= 1000 for a, b in spans)
    assert spans[0][0] == 0
    assert spans[-1][1] == len(text)
    assert all(b[0] < a[1] for a, b in pairwise(spans))  # overlap


def test_latin_windows_are_cut_between_words() -> None:
    text = " ".join(f"Halden{n}" for n in range(3000))
    spans = windows(text, window_tokens=500, overlap_tokens=50)
    assert all(text[a:b] == text[a:b].strip() for a, b in spans)
    assert all(b == len(text) or text[b].isspace() for _, b in spans)


def test_chunks_split_a_script_without_spaces_and_its_full_stops() -> None:
    sentence = "\u6e2f" * 300 + "\u3002"
    chunks = chunk_text(sentence * 4, [], PARAMS)
    assert len(chunks) > 4
    assert all(estimate_tokens(c.text) <= PARAMS.prose_tokens * 2 for c in chunks)


def test_chunk_spans_are_exactly_their_text() -> None:
    """RV-077: spans carried whitespace the text strips; table pieces carried the whole
    table's span."""
    table = "| District | Share |\n|---|---|\n" + "".join(
        f"| District {n} | {n}.0% |\n" for n in range(40)
    )
    text = "  Halden Bay reported figures.  \n" + table
    start = text.index("|")
    chunks = chunk_text(text, [(start, len(text))], PARAMS)
    prose = [c for c in chunks if not c.is_table]
    assert all(text[c.start : c.end] == c.text for c in prose)
    pieces = [c for c in chunks if c.is_table]
    assert len(pieces) > 2
    assert len({(c.start, c.end) for c in pieces}) == len(pieces)  # each its own rows
    for c in pieces:
        assert text[c.start : c.end] in c.text  # the piece's rows, under its header


def test_the_most_relevant_windows_are_kept_in_document_order() -> None:
    """RV-060 (owner: 4 per slot and source): ranked by hits for the city and the slot."""
    parts = ["filler text about ferries. " * 20] * 8
    parts[2] = "Halden Bay blood pressure survey results. " * 5
    parts[6] = "Halden Bay hypertension control in Halden Bay. " * 5
    text = "".join(parts)
    spans = [(sum(map(len, parts[:i])), sum(map(len, parts[: i + 1]))) for i in range(8)]
    chosen = pick_windows(text, spans, ["Halden Bay", "hypertension", "pressure"], 2)
    assert [n for n, _, _ in chosen] == [3, 7]  # numbered from 1, in document order
    assert len(pick_windows(text, spans, ["Halden Bay"], 4)) == 4
    assert pick_windows(text, spans[:3], [], 4) == [(1, *spans[0]), (2, *spans[1]), (3, *spans[2])]


async def test_no_new_window_starts_too_close_to_the_end() -> None:
    """RV-100 (owner: 60 s): its drafts could not be located and checked in time."""
    d: Any = SimpleNamespace(
        ledger=SimpleNamespace(time_left_s=lambda: 30.0),
        window=SimpleNamespace(stop_windows_below_s=60.0),
    )
    job = Window("src_1", {}, "text", 1, 1, 0, 4)
    assert await _extract_window(d, {}, job) is None


def test_pdf_tables_lose_their_empty_columns_and_rows() -> None:
    """RV-054: most separators in one statistical PDF marked empty cells."""
    rows: list[list[str | None]] = [
        ["District", None, "n", "", "%"],
        ["Halden Bay", None, "1 412", "", "23.0"],
        [None, None, None, None, None],
        ["Kestrel Point", "", "655", None, "20.7"],
    ]
    assert _pipe_table(rows) == (
        "| District | n | % |\n|---|---|---|\n| Halden Bay | 1 412 | 23.0 |\n"
        "| Kestrel Point | 655 | 20.7 |"
    )
