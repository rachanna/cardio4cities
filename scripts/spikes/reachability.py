"""Spike S-3: what this host can reach (BUILD_PLAN §2; BD-36, code review RV-107).

Run it on the deployed service before the first rehearsal, from the service's shell:

    python -m scripts.spikes.reachability [--sites FILE]

No model or search calls, no spend. The official APIs (WHO GHO, World Bank, DHS) are asked
for one row each through the gate's API path, within their published terms. Each site is
fetched exactly as a run fetches it: the crawl gate first (public address, pinned IP,
robots.txt, crawl delay), every request reserved on a budget ledger, and a block is
recorded, never worked around.

Sites come from a git-ignored file, one URL per line (`#` starts a comment), by default
`spike_results/s3_sites.txt`, so no real URL enters the repository. Per-site outcomes go to
`spike_results/S-3-reachability.md`; the printed summary (the APIs by name, sites counted
by outcome) is what the decision row records.
"""

import argparse
import asyncio
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from dotenv import load_dotenv

from app.adapters.fetch.httpx_pinned import PinnedFetcher
from app.adapters.fetch.robots_protego import ProtegoRobotsParser
from app.adapters.parse.documents import DocumentParser
from app.settings import load_settings
from app.workflow.budget import BudgetLedger, BudgetLimits
from app.workflow.collection import Collector
from app.workflow.runner import collection_params

OUT = Path(__file__).resolve().parents[2] / "spike_results"
DEFAULT_SITES = OUT / "s3_sites.txt"
DHS_PROBE = "https://api.dhsprogram.com/rest/dhs/indicators?f=json&perpage=1"
WALL_CLOCK_S = 900.0  # the spike's own limit, not a run's


def read_sites(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = (
        line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
    )
    return [line for line in lines if line]


def api_probes(structured: dict[str, str]) -> dict[str, str]:
    """One small request per official API: an indicator the registry uses, one row."""
    probes = {"dhs": DHS_PROBE}
    if "who_gho" in structured:
        probes["who_gho"] = f"{structured['who_gho'].rstrip('/')}/NCD_HYP_PREVALENCE_A?$top=1"
    if "world_bank" in structured:
        probes["world_bank"] = (
            f"{structured['world_bank'].rstrip('/')}/country/WLD/indicator/SP.POP.TOTL"
            "?format=json&per_page=1"
        )
    return probes


async def probe(sites: list[str]) -> tuple[dict[str, str], list[tuple[str, str, str]]]:
    settings = load_settings()
    cfg = settings.config
    ledger = BudgetLedger(
        BudgetLimits(
            wall_clock_s=WALL_CLOCK_S,
            searches=0,
            fetches=4 * (len(sites) + 3),  # redirects and robots.txt included
            tokens=0,
            cost_micro_usd=0,
            wind_down_at=1.0,
        )
    )
    collector = Collector(
        PinnedFetcher(), ProtegoRobotsParser(), DocumentParser(), ledger, collection_params(cfg)
    )
    structured = {name: p.base_url for name, p in cfg.structured.providers.items()}
    apis = {}
    for provider, url in api_probes(structured).items():
        got = await collector.fetch_api(url, provider)
        last = got.decisions[-1]
        status = got.result.status if got.result is not None else None
        apis[provider] = (
            "reachable" if got.result is not None else f"{last.outcome.value} {status or ''}"
        )
    rows = []
    for url in sites:
        collected = await collector.collect(url, [])
        last = collected.decisions[-1]
        if collected.outcome == "fetched":
            parsed = collected.parse_outcome
            outcome = f"fetched ({parsed.value if parsed else 'unparsed'})"
        elif collected.outcome == "http_error":
            outcome = f"http_error {collected.http_status}"
        else:
            outcome = last.outcome.value
        rows.append((url, outcome, last.reason))
    return apis, rows


def report(apis: dict[str, str], rows: list[tuple[str, str, str]]) -> str:
    when = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"# S-3 reachability, {when}", "", "## Official APIs", ""]
    lines += [f"- {provider}: {outcome}" for provider, outcome in sorted(apis.items())]
    lines += ["", "## Sites by outcome", ""]
    lines += [f"- {outcome}: {n}" for outcome, n in Counter(o for _, o, _ in rows).most_common()]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sites", type=Path, default=DEFAULT_SITES)
    args = parser.parse_args(argv)
    load_dotenv(".env", override=False)
    sites = read_sites(args.sites)
    if not sites:
        print(f"no sites listed in {args.sites}: the official APIs only", file=sys.stderr)
    apis, rows = asyncio.run(probe(sites))
    summary = report(apis, rows)
    OUT.mkdir(exist_ok=True)
    detail = [f"| {url} | {outcome} | {reason} |" for url, outcome, reason in rows]
    (OUT / "S-3-reachability.md").write_text(
        summary
        + "\n## Sites\n\n| URL | Outcome | Reason |\n|---|---|---|\n"
        + "\n".join(detail)
        + "\n",
        encoding="utf-8",
    )
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
