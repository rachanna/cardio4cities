"""Report rendering (LLD-2 §16 step 9): Markdown and HTML from templates. The PDF is the
same HTML without its head, laid out by the renderer port (the API layer calls it)."""

import re
from collections.abc import Mapping
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.report.assemble import Cited, Report

TEMPLATES = Path(__file__).resolve().parent / "templates"


def fact(c: Cited) -> str:
    """One fact line: the statement, its citation, then what a reader must know."""
    card = c.card
    notes = []
    if card.main_badge:
        notes.append(card.main_badge.label)
    notes += [b.label for b in card.other_badges]
    if card.status == "contested" and "Sources disagree" not in notes:
        notes.append("Sources disagree")
    if card.confidence:
        notes.append(card.confidence.label_word)
    if not card.period.stated:
        notes.append("period not stated")
    tail = f" ({'; '.join(notes)})" if notes else ""
    return f"{card.statement} [{c.citation}]{tail}"


def date(value: datetime | None) -> str:
    return value.date().isoformat() if value else "date not recorded"


def counts(summary: Mapping[str, Any]) -> list[str]:
    """Run counts from the run summary (LLD-1 §2.7), in plain words."""
    lines = []
    claims = summary.get("claims") or {}
    if claims:
        lines.append("Claims: " + ", ".join(f"{k} {v}" for k, v in sorted(claims.items())))
    sources = summary.get("sources") or {}
    if sources:
        blocked = sum((sources.get("blocked") or {}).values())
        unreachable = sum((sources.get("unreachable") or {}).values())
        lines.append(
            f"Sources: {sources.get('read', 0)} read, {blocked} blocked, {unreachable} unreachable"
        )
    if "cost_usd" in summary:
        lines.append(f"Model cost: ${float(summary['cost_usd']):.4f}")
    wall = (summary.get("time") or {}).get("wall_clock_ms")
    if wall:
        lines.append(f"Time: {int(wall) // 1000} s")
    return lines


@cache
def _env() -> Environment:
    """HTML templates are escaped; the Markdown one is plain text."""
    env = Environment(
        loader=FileSystemLoader(TEMPLATES),
        autoescape=select_autoescape(enabled_extensions=("html.j2",), default=False),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    env.globals.update(fact=fact, date=date, counts=counts)
    return env


def markdown(report: Report) -> str:
    text = _env().get_template("report.md.j2").render(r=report)
    return re.sub(r"\n{3,}", "\n\n", text)  # one blank line between blocks


def html(report: Report, pdf: bool = False) -> str:
    """The HTML download; with `pdf`, without the head and styles fpdf2 does not read."""
    return _env().get_template("report.html.j2").render(r=report, pdf=pdf)
