"""`poe reindex` (E-05, BD-56): the pure decisions behind a rebuild from Postgres."""

from app.ports.parse import ParsedDocument
from scripts.reindex import batches, choose_spans, mime_of

TEXT = "Halden Bay survey. | District | % |\n| Harbour | 31.2 |"


def test_stored_spans_win() -> None:
    assert choose_spans([[19, 52]], TEXT, None) == ([(19, 52)], "stored")


def test_reparsed_spans_count_only_when_the_text_is_identical() -> None:
    """Claim offsets refer to the stored text, so a re-parse that differs by one
    character must not decide where chunks are cut."""
    same = ParsedDocument(text=TEXT, tables=[(19, 52)])
    other = ParsedDocument(text=TEXT + " ", tables=[(19, 52)])

    assert choose_spans(None, TEXT, same) == ([(19, 52)], "reparsed")
    assert choose_spans(None, TEXT, other) == ([], "prose")
    assert choose_spans(None, TEXT, None) == ([], "prose")


def test_a_pdf_served_generically_is_a_pdf() -> None:
    assert mime_of("application/octet-stream", b"%PDF-1.7 ...") == "application/pdf"
    assert mime_of("text/html; charset=utf-8", b"<html>") == "text/html"


def test_batches_keep_every_item_in_order() -> None:
    assert batches(list(range(5)), 2) == [[0, 1], [2, 3], [4]]
