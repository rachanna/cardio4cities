"""Spike S-5: quote matching on real PDF tables (BUILD_PLAN §2; LLD-2 §4.1, §9.4).

Fetches two global WHO reports through the real crawl gate and pinned fetcher, parses
them with table extraction, asks a model to copy table rows and their values verbatim,
then runs exact §4.1 matching and reports the drop rate. Pass: under about 20% dropped.

Uses a local Ollama model (no cost); a small model copies less faithfully than the
production extractor, so the result is a pessimistic upper bound. Re-run with the
production extractor once spend is approved. Writes a summary only (no quoted figures).

    uv run poe spike pdf_quotes            # or: python -m scripts.spikes.pdf_quotes
"""

import argparse
import asyncio
import json
import re
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import yaml

from app.adapters.fetch.httpx_pinned import PinnedFetcher
from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser
from app.domain.params import QuoteParams
from app.settings import CONFIG_DIR
from app.workflow.collection import CollectionParams, Collector, FetchKind
from app.workflow.rules.quotes import QuoteDrop, match_quote

# Global reports only: no city or country URL is ever written into the repository.
DOCUMENTS = {
    "who_ncd_progress_monitor_2022": (
        "https://iris.who.int/server/api/core/bitstreams/db06a907-0d4b-43d7-a49a-a7eb3623e489/content"
    ),
    "who_global_hypertension_report_2023": (
        "https://iris.who.int/server/api/core/bitstreams/d7a81217-efd0-47ce-a78d-164f0f0f8dd2/content"
    ),
}
KEYWORDS = ["hypertension", "blood pressure", "prevalence", "mortality", "diabetes", "%"]
UA = "CARDIO4CitiesResearchBot/0.1 (+https://github.com/rachanna/cardio4cities)"
# Each run writes here; results/S-5-pdf-quotes.md is the curated record.
RESULTS = Path(__file__).with_name("results") / "S-5-pdf-quotes-latest-run.md"

PROMPT = """You copy text exactly. Below is part of a report, between <source> tags.
Choose up to {n} lines that contain a number. For each, copy the line EXACTLY as it appears,
character for character (including any | separators), and copy one number from that line
exactly as written in "value". Do not fix spelling, spacing or punctuation.
Answer with JSON only: {{"items": [{{"quote": "...", "value": "..."}}]}}

<source>
{table}
</source>"""


NUMERIC_LINE = re.compile(r"\d[\d.,]*\s*%?.*\d")
BLOCK_LINES = 20


def numeric_blocks(text: str, pages: list[tuple[int, int]], limit: int) -> list[str]:
    """Runs of page-text lines holding numbers: how report tables without ruled grids
    reach the extractor. Taken from evenly spread pages to sample the whole report."""
    bounds = [start for _, start in pages] + [len(text)]
    candidates: list[str] = []
    for start, end in pairwise(bounds):
        lines = [ln for ln in text[start:end].splitlines() if NUMERIC_LINE.search(ln)]
        if len(lines) >= 3 and any(k in text[start:end].lower() for k in KEYWORDS[:5]):
            candidates.append("\n".join(lines[:BLOCK_LINES]))
    step = max(1, len(candidates) // limit) if candidates else 1
    return candidates[::step][:limit]


class Unlimited:
    async def reserve(self, kind: FetchKind) -> None:
        pass


@dataclass
class Tally:
    tables: int = 0
    quotes: int = 0
    reasons: Counter[str] = field(default_factory=Counter)
    window_reasons: Counter[str] = field(default_factory=Counter)  # matched within shown text


def ask_ollama(base: str, model: str, prompt: str) -> list[dict[str, str]]:
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }
    ).encode()
    request = urllib.request.Request(  # noqa: S310 (local Ollama URL from the command line)
        f"{base}/api/generate", body, {"content-type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=300) as response:  # noqa: S310 (local Ollama)
        text = json.loads(response.read())["response"]
    try:
        items = json.loads(text).get("items", [])
    except (json.JSONDecodeError, AttributeError):
        return []
    return [i for i in items if isinstance(i, dict) and i.get("quote") and i.get("value")]


async def document(
    collector: Collector, name: str, url: str, cache: Path | None
) -> tuple[str, list[tuple[int, int]], list[tuple[int, int]]] | None:
    """Parsed text, tables and pages; a cached copy is reused only after a gated fetch."""
    cached = cache / f"{name}.pdf" if cache else None
    if cached is not None and cached.exists():
        doc = DocumentParser().parse_pdf(cached.read_bytes(), KEYWORDS)
        print(f"{name}: cached copy of an earlier gated fetch")
        return doc.text, doc.tables, doc.pages
    result = await collector.collect(url, KEYWORDS)
    decision = result.final_decision
    print(f"{name}: {decision.outcome.value} ({decision.reason}); parse={result.parse_outcome}")
    if result.document is None:
        return None
    if cached is not None:
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(result.raw)
    return result.document.text, result.document.tables, result.document.pages


async def run(
    base: str,
    model: str,
    max_tables: int,
    per_table: int,
    robots_timeout: float,
    cache: Path | None,
) -> dict[str, Tally]:
    collector = Collector(
        PinnedFetcher(),
        ProtegoRobotsParser(),
        DocumentParser(),
        Unlimited(),
        CollectionParams(UA, (80, 443), 1.0, 2, 30_000_000, 10.0, 120.0, robots_timeout),
    )
    quote_config = yaml.safe_load((CONFIG_DIR / "local.yaml").read_text("utf-8"))["quote"]
    params = QuoteParams(**quote_config)  # the shipped tunables, not literals
    tallies: dict[str, Tally] = {}
    for name, url in DOCUMENTS.items():
        tally = tallies[name] = Tally()
        parsed = await document(collector, name, url, cache)
        if parsed is None:
            continue
        text, tables, pages = parsed
        segments = [text[s:e] for s, e in tables[:max_tables]]
        segments += numeric_blocks(text, pages, max_tables)
        for segment in segments:
            tally.tables += 1
            for item in ask_ollama(base, model, PROMPT.format(n=per_table, table=segment)):
                tally.quotes += 1
                outcome = match_quote(item["quote"], text, params, item["value"])
                tally.reasons[outcome.reason if isinstance(outcome, QuoteDrop) else "matched"] += 1
                # Same rule, scoped to the text the model was shown (what an extraction
                # window would be): uniqueness then cannot be confused by other pages.
                scoped = match_quote(item["quote"], segment, params, item["value"])
                key = scoped.reason if isinstance(scoped, QuoteDrop) else "matched"
                tally.window_reasons[key] += 1
        print(f"  tables {tally.tables}, quotes {tally.quotes}, outcomes {dict(tally.reasons)}")
        print(f"  scoped to shown text: {dict(tally.window_reasons)}")
    return tallies


def write_summary(tallies: dict[str, Tally], model: str) -> float:
    total = sum(t.quotes for t in tallies.values())
    matched = sum(t.reasons["matched"] for t in tallies.values())
    drop = 1 - matched / total if total else 1.0
    lines = [
        "# Spike S-5: PDF quote matching",
        "",
        f"Extractor stand-in: local Ollama `{model}` (pessimistic). Matching: LLD-2 §4.1, exact.",
        "",
        "| Document | Segments (tables + numeric text) | Quotes | Matched | Dropped by reason |",
        "|---|---|---|---|---|",
    ]
    for name, t in tallies.items():
        reasons = t.reasons
        drops = (
            ", ".join(f"{k} {v}" for k, v in sorted(reasons.items()) if k != "matched") or "none"
        )
        lines.append(f"| {name} | {t.tables} | {t.quotes} | {reasons['matched']} | {drops} |")
    scoped_reasons: Counter[str] = Counter()
    for t in tallies.values():
        scoped_reasons.update(t.window_reasons)
    scoped_drop = 1 - scoped_reasons["matched"] / total if total else 1.0
    scoped = ", ".join(f"{k} {v}" for k, v in sorted(scoped_reasons.items()))
    lines += [
        "",
        f"**Overall drop rate: {drop:.1%}** of {total} quotes (pass bar: under about 20%).",
        "",
        f"Uniqueness scoped to the text the model was shown: **{scoped_drop:.1%}** dropped "
        f"({scoped}).",
    ]
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return drop


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--ollama", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen2.5:3b")
    parser.add_argument("--max-tables", type=int, default=15)
    parser.add_argument("--per-table", type=int, default=3)
    parser.add_argument("--robots-timeout", type=float, default=15.0)  # fetch.robots_timeout_s
    parser.add_argument("--cache-dir", type=Path, default=None, help="reuse downloads (scratch)")
    args = parser.parse_args()
    tallies = asyncio.run(
        run(
            args.ollama,
            args.model,
            args.max_tables,
            args.per_table,
            args.robots_timeout,
            args.cache_dir,
        )
    )
    drop = write_summary(tallies, args.model)
    return 0 if drop < 0.20 else 1


if __name__ == "__main__":
    sys.exit(main())
