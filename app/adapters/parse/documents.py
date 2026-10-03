"""ParserPort: HTML with trafilatura, PDF with pdfplumber (LLD-2 §9.4, BD-07).

HTML: main content only, tables kept as pipe tables with their header row.
PDF: page text with `[page N]` markers; tables extracted only on pages whose text
contains a slot keyword, rendered as pipe tables after the page text.
"""

import io
import re
from datetime import date

import pdfplumber
import trafilatura

from app.ports.parse import ParsedDocument
from app.settings import Settings

_TABLE_LINE = re.compile(r"^\|.*\|\s*$")


def _table_spans(text: str) -> list[tuple[int, int]]:
    """Blocks of consecutive lines that start and end with '|'."""
    spans: list[tuple[int, int]] = []
    start: int | None = None
    offset = 0
    for line in text.splitlines(keepends=True):
        if _TABLE_LINE.match(line.rstrip("\r\n")):
            if start is None:
                start = offset
        elif start is not None:
            spans.append((start, offset))
            start = None
        offset += len(line)
    if start is not None:
        spans.append((start, offset))
    return spans


# Spike S-5: pdfplumber also reports layout boxes of prose as "tables". A real table has
# at least two rows and two columns, short cells and at least one number; anything else
# is left to the page text, which already holds its words (BD-07).
MAX_MEDIAN_CELL_WORDS = 8
_NUMBER = re.compile(r"\d")


def is_tabular(rows: list[list[str | None]]) -> bool:
    filled = [r for r in rows if any((c or "").strip() for c in r)]
    if len(filled) < 2 or max((len(r) for r in filled), default=0) < 2:
        return False
    cells = [(c or "").split() for r in filled for c in r if (c or "").strip()]
    lengths = sorted(len(words) for words in cells)
    median = lengths[len(lengths) // 2]
    has_number = any(_NUMBER.search(" ".join(words)) for words in cells)
    return median <= MAX_MEDIAN_CELL_WORDS and has_number


def _pipe_table(rows: list[list[str | None]]) -> str:
    cleaned = [[(cell or "").replace("\n", " ").strip() for cell in row] for row in rows if row]
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    lines = ["| " + " | ".join(cleaned[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in cleaned[1:]]
    return "\n".join(lines)


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


class DocumentParser:
    def parse_html(self, content: bytes, url: str) -> ParsedDocument:
        html = content.decode("utf-8", errors="replace")
        text = trafilatura.extract(
            html,
            url=url,
            output_format="txt",
            include_tables=True,
            include_comments=False,
            include_links=False,
            favor_precision=True,
        )
        meta = trafilatura.extract_metadata(html, default_url=url)
        info = meta.as_dict() if meta else {}
        body = (text or "").replace(" \n", "\n")
        return ParsedDocument(
            text=body,
            title=info.get("title"),
            language=info.get("language"),
            published_date=_date(info.get("date")),
            tables=_table_spans(body),
        )

    def parse_pdf(self, content: bytes, table_keywords: list[str]) -> ParsedDocument:
        keywords = [k.lower() for k in table_keywords if k]
        parts: list[str] = []
        pages: list[tuple[int, int]] = []
        tables: list[tuple[int, int]] = []
        length = 0
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for number, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                block = f"[page {number}]\n{page_text}\n"
                pages.append((number, length))
                if keywords and any(k in page_text.lower() for k in keywords):
                    for rows in page.extract_tables():
                        if not is_tabular(rows):
                            continue
                        rendered = _pipe_table(rows)
                        if rendered:
                            start = length + len(block)
                            block += rendered + "\n"
                            tables.append((start, start + len(rendered) + 1))
                parts.append(block)
                length += len(block)
            title = (pdf.metadata or {}).get("Title")
        return ParsedDocument(text="".join(parts), title=title or None, pages=pages, tables=tables)


def make(settings: Settings) -> DocumentParser:
    return DocumentParser()
