"""ParserPort: HTML with trafilatura, PDF with pdfplumber (LLD-2 §9.4, BD-07).

HTML: main content only, tables kept as pipe tables with their header row. Spanning
cells are expanded first, so every row carries its own label cells (BD-10).
PDF: page text with `[page N]` markers; tables extracted only on pages whose text
contains a slot keyword, rendered as pipe tables after the page text.
"""

import copy
import io
import logging
import re
from datetime import date

import pdfplumber
import trafilatura
from lxml import etree
from lxml import html as lxml_html

from app.domain.charset import decode_text
from app.domain.vocab import DatePrecision
from app.ports.parse import ParsedDocument
from app.settings import Settings

log = logging.getLogger(__name__)

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
    cleaned = [r for r in cleaned if any(r)]  # rows with no text at all
    if not cleaned:
        return ""
    width = max(len(r) for r in cleaned)
    cleaned = [r + [""] * (width - len(r)) for r in cleaned]
    # Columns empty in every row: in one statistical PDF 79% of the separators marked
    # empty cells, and quotes copied across them failed (BD-29; code review RV-054)
    keep = [c for c in range(width) if any(r[c] for r in cleaned)]
    cleaned = [[r[c] for c in keep] for r in cleaned]
    width = len(keep)
    lines = ["| " + " | ".join(cleaned[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in cleaned[1:]]
    return "\n".join(lines)


# Spike D2-3: a label cell spanning two rows (rowspan) was kept on the first row only, so
# the second row's values lost their label and no verbatim quote could hold both. The
# cell belongs to every row it spans, so it is copied into each; a column span is padded
# with empty cells to keep columns aligned. Spans are capped so markup cannot inflate a
# page (HTML allows rowspan up to 65534).
MAX_SPAN = 50


def _span(cell: etree._Element, name: str) -> int:
    try:
        value = int(str(cell.get(name, "1")).strip() or "1")
    except ValueError:
        return 1
    return max(1, min(value, MAX_SPAN))


def _rows(table: etree._Element) -> list[etree._Element]:
    return table.xpath("./tr | ./thead/tr | ./tbody/tr | ./tfoot/tr")  # type: ignore[no-any-return]


Pending = dict[int, tuple[etree._Element, int]]  # column -> (cell to copy, rows left)


def _fill(pending: Pending, out: list[etree._Element], col: int) -> int:
    """Place copies of row-spanning cells from `col` onwards; return the next column."""
    while col in pending:
        cell, left = pending.pop(col)
        out.append(copy.deepcopy(cell))
        if left > 1:
            pending[col] = (cell, left - 1)
        col += 1
    return col


def expand_spans(markup: str) -> str:
    """Copy each row-spanning cell into the rows it covers; pad column spans."""
    if "rowspan" not in markup.lower() and "colspan" not in markup.lower():
        return markup
    root = lxml_html.document_fromstring(markup)
    for table in root.iter("table"):
        pending: Pending = {}
        for tr in _rows(table):
            cells = [c for c in tr if c.tag in ("td", "th")]
            out: list[etree._Element] = []
            col = 0
            for cell in cells:
                col = _fill(pending, out, col)
                rows, cols = _span(cell, "rowspan"), _span(cell, "colspan")
                for name in ("rowspan", "colspan"):
                    cell.attrib.pop(name, None)
                pads = [etree.Element(cell.tag) for _ in range(cols - 1)]
                out += [cell, *pads]
                if rows > 1:
                    for offset, source in enumerate([cell, *pads]):
                        pending[col + offset] = (copy.deepcopy(source), rows - 1)
                col += cols
            while any(c >= col for c in pending):
                nxt = min(c for c in pending if c >= col)
                out.extend(etree.Element("td") for _ in range(nxt - col))  # keep alignment
                col = _fill(pending, out, nxt)
            for cell in cells:
                tr.remove(cell)
            tr.extend(out)
    return str(lxml_html.tostring(root, encoding="unicode"))


def _date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


_LANG = re.compile(r"""<html[^>]*?\blang\s*=\s*["']?([A-Za-z]{2,3})\b""", re.IGNORECASE)
HEAD_SCAN_CHARS = 20_000


def _lang(html: str) -> str | None:
    """The page's declared language (`<html lang>`), primary subtag only."""
    found = _LANG.search(html[:HEAD_SCAN_CHARS])
    return found.group(1).lower() if found else None


def _precision(html: str, published: date | None) -> DatePrecision | None:
    """As precise as the page's own head states the date: a full date, a month, or only
    the year (a metadata "2024" read as 2024-01-01 is a year, not a day)."""
    if published is None:
        return None
    head = html[:HEAD_SCAN_CHARS]
    if published.isoformat() in head:
        return DatePrecision.DAY
    if published.strftime("%Y-%m") in head:
        return DatePrecision.MONTH
    return DatePrecision.YEAR


class DocumentParser:
    """`max_pages`: a PDF is read up to this page (`fetch.pdf_max_pages`, BD-27)."""

    def __init__(self, max_pages: int | None = None) -> None:
        self._max_pages = max_pages

    def parse_html(self, content: bytes, url: str, charset: str | None = None) -> ParsedDocument:
        try:
            return self._html(content, url, charset)
        except Exception as exc:  # a page the libraries cannot read is unreadable (BD-21)
            log.warning("parse: unreadable HTML (%s)", type(exc).__name__)
            return ParsedDocument(text="")

    def parse_pdf(self, content: bytes, table_keywords: list[str]) -> ParsedDocument:
        try:
            return self._pdf(content, table_keywords)
        except Exception as exc:  # malformed or encrypted PDF: unreadable (BD-21)
            log.warning("parse: unreadable PDF (%s)", type(exc).__name__)
            return ParsedDocument(text="")

    def _html(self, content: bytes, url: str, charset: str | None) -> ParsedDocument:
        html = expand_spans(decode_text(content, charset, html=True))
        text = trafilatura.extract(
            html,
            url=url,
            output_format="txt",
            include_tables=True,
            include_comments=False,
            include_links=False,
            favor_precision=True,
        )
        # Metadata only: `extensive` date search reads body text, so "31 % in 2019" became
        # a publication date of 2019-01-01 (BD-22; never infer labels)
        meta = trafilatura.extract_metadata(html, default_url=url, extensive=False)
        info = meta.as_dict() if meta else {}
        published = _date(info.get("date"))
        body = (text or "").replace(" \n", "\n")
        return ParsedDocument(
            text=body,
            title=info.get("title"),
            language=info.get("language") or _lang(html),
            published_date=published,
            published_precision=_precision(html, published),
            tables=_table_spans(body),
        )

    def _pdf(self, content: bytes, table_keywords: list[str]) -> ParsedDocument:
        keywords = [k.lower() for k in table_keywords if k]
        parts: list[str] = []
        pages: list[tuple[int, int]] = []
        tables: list[tuple[int, int]] = []
        length = 0
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            pages_read = pdf.pages[: self._max_pages] if self._max_pages else pdf.pages
            for number, page in enumerate(pages_read, start=1):
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
    return DocumentParser(settings.config.fetch.pdf_max_pages)
