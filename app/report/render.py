"""Report rendering (LLD-2 §16 step 9): Markdown and HTML from templates. The PDF is the
same HTML without its head, laid out by the renderer port (the API layer calls it)."""

import re
from collections.abc import Mapping
from datetime import datetime
from functools import cache
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

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


def confidence(c: Cited) -> str:
    """The confidence word for a table cell: High, Medium or Low."""
    card = c.card.confidence
    return card.label_word.split()[0] if card else "—"


def caveats(c: Cited) -> str:
    """What a reader must know about a fact, most severe first; "—" when nothing."""
    card = c.card
    notes = [card.main_badge.label] if card.main_badge else []
    notes += [b.label for b in card.other_badges]
    if card.status == "contested" and "Sources disagree" not in notes:
        notes.append("Sources disagree")
    if not card.period.stated and card.kind == "statistic":
        notes.append("Period not stated")  # a statement is dated by its publication (D4-3)
    return ", ".join(notes) or "—"


def refs(c: Cited) -> str:
    """ "[3]", or "[3][7]" when a repeat of the fact came from another source (D4-3)."""
    return "".join(f"[{n}]" for n in dict.fromkeys((c.citation, *c.also)))


def short_url(url: str) -> str:
    """Host and path without the query: readable in print; the link keeps the full URL."""
    parts = urlsplit(url)
    path = parts.path.rstrip("/")
    return f"{parts.netloc}{path}" if len(path) <= 60 else f"{parts.netloc}{path[:57]}…"


def roles(models: Mapping[str, str]) -> list[tuple[str, str, str]]:
    """(role, model, prompt version) from `run.versions` ("model / prompt")."""
    out = []
    for role, version in models.items():
        model, _, prompt = str(version).partition(" / ")
        out.append((role.capitalize(), model, prompt or "—"))
    return out


def cell(text: Any) -> str:
    """A Markdown table cell: pipes escaped, one line."""
    return " ".join(str(text).split()).replace("|", r"\|")


def plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def date(value: datetime | None) -> str:
    return value.date().isoformat() if value else "date not recorded"


STAGE_WORDS = {
    "search": "search",
    "crawl_gate": "permission check",
    "fetch_parse": "page reading",
    "extract": "extraction",
    "match_quotes": "quote matching",
    "verify": "fact checking",
    "consistency": "consistency check",
    "write": "storage",
    "wave0": "official data",
}


def failed_steps(summary: Mapping[str, Any]) -> str | None:
    """'55 extraction steps, 2 page reading steps', or None when nothing failed: a run that
    lost steps says so, so an empty section is not mistaken for an empty city (D4-3)."""
    failed = {k: int(v) for k, v in (summary.get("failed_steps") or {}).items() if int(v)}
    if not failed:
        return None
    parts = sorted(failed.items(), key=lambda kv: -kv[1])
    return ", ".join(
        f"{n} {STAGE_WORDS.get(stage, stage.replace('_', ' '))} {'step' if n == 1 else 'steps'}"
        for stage, n in parts
    )


# Steps whose failure cannot lose a finding: they index page text for question
# answering only (BD-52). Run details still lists them.
INDEX_ONLY_STAGES = frozenset({"index_chunks"})


def lost_steps(summary: Mapping[str, Any]) -> str | None:
    """`failed_steps` without the index-only stages: what the "Incomplete run" warning
    names, since only these failures can hide a finding (BD-52)."""
    failed = {
        k: v for k, v in (summary.get("failed_steps") or {}).items() if k not in INDEX_ONLY_STAGES
    }
    return failed_steps({"failed_steps": failed})


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
    lost = failed_steps(summary)
    if lost:
        lines.append(f"Failed steps: {lost}")
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
    env.globals.update(
        fact=fact, date=date, counts=counts, confidence=confidence, caveats=caveats,
        short_url=short_url, roles=roles, plural=plural, failed_steps=failed_steps,
        lost_steps=lost_steps, refs=refs,
    )  # fmt: skip
    env.filters["cell"] = cell
    return env


def markdown(report: Report) -> str:
    text = _env().get_template("report.md.j2").render(r=report)
    return re.sub(r"\n{3,}", "\n\n", text)  # one blank line between blocks


def html(report: Report, pdf: bool = False) -> str:
    """The HTML download; with `pdf`, without the head and styles fpdf2 does not read."""
    return _env().get_template("report.html.j2").render(r=report, pdf=pdf)
