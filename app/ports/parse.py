"""Document parsing (LLD-2 §9.4). `text` is what claim offsets refer to."""

from datetime import date
from typing import Protocol

from pydantic import BaseModel, ConfigDict


class ParsedDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    title: str | None = None
    language: str | None = None
    published_date: date | None = None
    tables: list[tuple[int, int]] = []  # [start, end) offsets of table blocks in `text`
    pages: list[tuple[int, int]] = []  # (page number, start offset) for PDFs


class ParserPort(Protocol):
    def parse_html(self, content: bytes, url: str) -> ParsedDocument: ...

    def parse_pdf(self, content: bytes, table_keywords: list[str]) -> ParsedDocument:
        """Tables are extracted only on pages whose text contains a keyword."""
        ...
