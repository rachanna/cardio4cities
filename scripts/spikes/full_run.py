"""Spike S-6: one full live run, all 16 slots, profile `local-quality` with Brave search
(BUILD_PLAN D2-5, BD-14). Costs money: ask the owner first. Model spend is capped by
`--max-usd` (the run's `budget.cost_micro_usd`); searches are capped by `budget.searches`
(Brave Search plan, about $0.005 each).

The city is typed at run time and never written into the repository. The full report,
which names the city, goes to `spike_results/` (git-ignored); a counts-only summary,
labelled by the `--label` given (for example data-rich or sparse), goes to
`scripts/spikes/results/`.

    uv run python -m scripts.spikes.full_run --city "<name>" --label data-rich [--pick 0]
    uv run python -m scripts.spikes.full_run --report <run_id> --label data-rich  # no spend
"""

import argparse
import asyncio
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from sqlalchemy import text

from app.container import build_container
from app.main import check_graph_marker
from app.settings import CONFIG_DIR, Settings, load_settings
from app.workflow.runner import RunManager

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "spike_results"
RESULTS = Path(__file__).parent / "results"
TARGET_S = 420  # the 7-minute target (budget.wall_clock_s, BD-15)


def configured(max_usd: float) -> Settings:
    """`local-quality` models and stores, Brave search, the model spend cap. Written as a
    config file (git-ignored) so the Brave key is resolved like any configured secret."""
    os.environ["APP_ENV"] = "local-quality"
    raw = yaml.safe_load((CONFIG_DIR / "local-quality.yaml").read_text(encoding="utf-8"))
    deployed = yaml.safe_load((CONFIG_DIR / "deployed.yaml").read_text(encoding="utf-8"))
    raw["search"] = {"provider": "brave", "mode": "links_only", "api_key_env": "BRAVE_API_KEY",
                     "rate_per_s": deployed["search"]["rate_per_s"]}  # fmt: skip
    raw["budget"]["cost_micro_usd"] = int(max_usd * 1e6)
    folder = RAW_DIR / "s6-config"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "local-quality.yaml").write_text(yaml.safe_dump(raw), encoding="utf-8")
    return load_settings(config_dir=folder)


async def run(city: str, pick: int, label: str, max_usd: float) -> int:
    load_dotenv(ROOT / ".env", override=False)
    settings = configured(max_usd)
    container = build_container(settings)
    try:
        relational = container.relational
        if relational is None:
            print("no relational store configured")
            return 1
        await check_graph_marker(container.graph, settings.config.embeddings.key)
        candidates = await relational.reference.search_places(city)
        for n, c in enumerate(candidates[:5]):
            print(f"  [{n}] {c['name']}, {c['admin1_name']}, {c['country_name']}"
                  f" (pop {c['population']})")  # fmt: skip
        if not candidates:
            print("no place matched")
            return 1
        chosen = candidates[pick]
        print(f"researching [{pick}] {chosen['name']}, {chosen['country_name']}: all slots")
        manager = RunManager(container, settings)
        started_at = time.monotonic()
        started = await manager.start(str(chosen["gazetteer_id"]))
        await manager.wait(started.run_id)
        elapsed = time.monotonic() - started_at
        return await report(container, started.run_id, label, elapsed, max_usd)
    finally:
        await container.close()


async def report_only(run_id: str, label: str, max_usd: float) -> int:
    load_dotenv(ROOT / ".env", override=False)
    container = build_container(configured(max_usd))
    try:
        row = await container.relational.runs.run_row(run_id)  # type: ignore[union-attr]
        elapsed = (row["finished_at"] - row["started_at"]).total_seconds() if row else 0.0
        return await report(container, run_id, label, elapsed, max_usd)
    finally:
        await container.close()


TLS_CAUSES = {
    "expired": "has expired",
    "self_signed": "is self-signed",
    "hostname_mismatch": "does not match the host name",
    "issuer_missing": "chain is incomplete",
    "untrusted": "could not be verified",
    "issuer_url_refused": "issuer certificate URL was refused",
}


async def certificate_causes(relational: Any, run_id: str) -> dict[str, int]:
    """Crawl decisions whose reason names a certificate cause (BD-15); a completed chain
    leaves no trace here because the site was read."""
    async with relational._engine.connect() as conn:
        rows = await conn.execute(
            text("SELECT reason FROM crawl_decision WHERE run_id = :r AND reason LIKE '%TLS%'"),
            {"r": run_id},
        )
        reasons = [r.reason for r in rows]
    return {k: n for k, words in TLS_CAUSES.items() if (n := sum(words in x for x in reasons))}


async def report(container: Any, run_id: str, label: str, elapsed: float, max_usd: float) -> int:
    relational = container.relational
    run = await relational.runs.run_row(run_id)
    summary: dict[str, Any] = run["summary"] or {}
    slots = await relational.runs.slot_results(run_id)
    events = await relational.runs.events_after(run_id, 0, 20_000)
    budget = summary.get("budget", {})
    tls = await certificate_causes(relational, run_id)
    searches = int(budget.get("searches", 0))
    search_usd = searches * 0.005
    model_usd = float(summary.get("cost_usd", 0))
    kinds = Counter(e["type"] for e in events)
    lines = [
        f"# S-6 full run ({label}): counts only, no city data",
        "",
        f"- status: {run['status']}; wall clock {elapsed:.0f} s against the {TARGET_S} s target",
        f"- model cost ${model_usd:.3f} of the ${max_usd:.2f} cap; Brave searches {searches}"
        f" (about ${search_usd:.3f}); total about ${model_usd + search_usd:.3f}",
        f"- busy time per stage (ms, summed across parallel slots): {summary['time']['busy_ms']}",
        f"- cost and tokens per model: {summary.get('models')}",
        f"- slots by status: {summary.get('slots')}",
        f"- claims by outcome: {summary.get('claims')}",
        f"- dropped by reason: {summary.get('dropped')}",
        f"- certificate outcomes (crawl decisions by TLS cause, BD-15): {tls}",
        f"- re-plan rounds used: {sum(s['replans_used'] for s in slots)} across"
        f" {sum(1 for s in slots if s['replans_used'])} slots",
        f"- sources: {summary.get('sources')}",
        f"- budget used: searches {searches}, fetches {budget.get('fetches')}, robots"
        f" {budget.get('robots')}, model calls {budget.get('model_calls')}, tokens in"
        f" {budget.get('tokens_in')} out {budget.get('tokens_out')}, refused"
        f" {budget.get('refused')}",
        f"- budget warnings: {[e['payload'] for e in events if e['type'] == 'budget_warning']}",
        f"- events: {dict(sorted(kinds.items()))}",
        "",
        "| slot | status | flags | re-plans | queries | sources | best claims |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in slots:
        lines.append(
            f"| {s['slot_id']} | {s['status']} | {','.join(s['flags']) or '-'} |"
            f" {s['replans_used']} | {len(s['queries_tried'])} | {len(s['sources_checked'])} |"
            f" {len(s['best_claim_ids'])} |"
        )
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"S-6-full-run-{label}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    RAW_DIR.mkdir(exist_ok=True)
    detail = {"run_id": run_id, "summary": summary, "slots": slots, "tls": tls,
              "elapsed_s": round(elapsed), "status": run["status"]}  # fmt: skip
    (RAW_DIR / f"S-6-{label}-{run_id}.json").write_text(
        json.dumps(detail, indent=2, default=str), encoding="utf-8"
    )
    print("\n".join(lines))
    print("\n== gap notes (stay out of the repository) ==")
    for s in slots:
        print(f"  {s['slot_id']} {s['status']:<20} {s['gap_note'] or ''}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", help="never saved in the repository")
    parser.add_argument("--pick", type=int, default=0)
    parser.add_argument("--label", required=True, help="data-rich or sparse")
    parser.add_argument("--max-usd", type=float, default=5.0)
    parser.add_argument("--report", metavar="RUN_ID", help="report an existing run only")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    # A selector loop, as on Linux, so the checkpointer runs as it will when deployed
    loop = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    if args.report:
        sys.exit(asyncio.run(report_only(args.report, args.label, args.max_usd), loop_factory=loop))
    if not args.city:
        parser.error("give --city; it is never saved")
    sys.exit(asyncio.run(run(args.city, args.pick, args.label, args.max_usd), loop_factory=loop))
