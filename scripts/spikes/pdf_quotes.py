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
import sys
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.adapters.fetch.httpx_pinned import PinnedFetcher
from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser
from app.domain.params import QuoteParams
from app.workflow.collection import CollectionParams, Collector, FetchKind
from app.workflow.rules.quotes import QuoteDrop, match_quote

# Global reports only: no city or country URL is ever written into the repository.
DOCUMENTS = {
    "who_ncd_progress_monitor_2022": (
        "https://iris.who.int/server/api/core/bitstreams/db06a907-0d4b-43d7-a49a-a7eb3623e489/content"
    ),
    "who_global_hypertension_report_2023": (
        "https://iris.who.int/server/api/core/bitstreams/8afcdf64-f092-4e81-8402-05ba6c697ffc/content"
    ),
}
KEYWORDS = ["hypertension", "blood pressure", "prevalence", "mortality", "diabetes", "%"]
UA = "CARDIO4CitiesResearchBot/0.1 (+https://github.com/rachanna/cardio4cities)"
RESULTS = Path(__file__).with_name("results") / "S-5-pdf-quotes.md"

PROMPT = """You copy text exactly. Below is a table from a report, between <source> tags.
Choose up to {n} rows that contain a number. For each, copy the row EXACTLY as it appears,
character for character, including the | separators, and copy one number from that row
exactly as written in "value". Do not fix spelling, spacing or punctuation.
Answer with JSON only: {{"items": [{{"quote": "...", "value": "..."}}]}}

<source>
{table}
</source>"""


class Unlimited:
    async def reserve(self, kind: FetchKind) -> None:
        pass


@dataclass
class Tally:
    tables: int = 0
    quotes: int = 0
    reasons: Counter[str] = field(default_factory=Counter)


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


async def run(
    base: str, model: str, max_tables: int, per_table: int, robots_timeout: float
) -> dict[str, Tally]:
    collector = Collector(
        PinnedFetcher(),
        ProtegoRobotsParser(),
        DocumentParser(),
        Unlimited(),
        CollectionParams(UA, (80, 443), 1.0, 2, 30_000_000, 10.0, 120.0, robots_timeout),
    )
    params = QuoteParams(min_words=6, max_words=60)
    tallies: dict[str, Tally] = {}
    for name, url in DOCUMENTS.items():
        tally = tallies[name] = Tally()
        result = await collector.collect(url, KEYWORDS)
        decision = result.final_decision
        print(f"{name}: {decision.outcome.value} ({decision.reason}); parse={result.parse_outcome}")
        if result.document is None:
            continue
        text = result.document.text
        for start, end in result.document.tables[:max_tables]:
            tally.tables += 1
            for item in ask_ollama(base, model, PROMPT.format(n=per_table, table=text[start:end])):
                tally.quotes += 1
                outcome = match_quote(item["quote"], text, params, item["value"])
                tally.reasons[outcome.reason if isinstance(outcome, QuoteDrop) else "matched"] += 1
        print(f"  tables {tally.tables}, quotes {tally.quotes}, outcomes {dict(tally.reasons)}")
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
        "| Document | Tables | Quotes | Matched | Dropped by reason |",
        "|---|---|---|---|---|",
    ]
    for name, t in tallies.items():
        reasons = t.reasons
        drops = (
            ", ".join(f"{k} {v}" for k, v in sorted(reasons.items()) if k != "matched") or "none"
        )
        lines.append(f"| {name} | {t.tables} | {t.quotes} | {reasons['matched']} | {drops} |")
    lines += [
        "",
        f"**Overall drop rate: {drop:.1%}** of {total} quotes (pass bar: under about 20%).",
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
    parser.add_argument("--robots-timeout", type=float, default=5.0)
    args = parser.parse_args()
    tallies = asyncio.run(
        run(args.ollama, args.model, args.max_tables, args.per_table, args.robots_timeout)
    )
    drop = write_summary(tallies, args.model)
    return 0 if drop < 0.20 else 1


if __name__ == "__main__":
    sys.exit(main())
