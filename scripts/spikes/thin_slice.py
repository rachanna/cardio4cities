"""D2-3 live check: one real research run of one slot through the whole graph, with the
configured adapters (live search, crawl gate, fetch, models). Costs money: ask the
owner first. Spend is capped below the approved amount by `--max-usd`.

The city is typed at run time and never written into the repository: the saved
summary holds counts only. Claims, quotes and URLs are printed to the terminal.

    uv run python -m scripts.spikes.thin_slice --city "<name>" [--pick 0] [--slot S04]
    uv run python -m scripts.spikes.thin_slice --report <run_id>   # no new spend
"""

import argparse
import asyncio
import os
import sys
import time
from collections import Counter
from dataclasses import replace
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text

from app.container import build_container
from app.settings import Settings, load_settings
from app.workflow.runner import RunManager

RESULTS = Path(__file__).parent / "results" / "D2-3-thin-slice-latest-run.md"


def capped(settings: Settings, max_usd: float) -> Settings:
    budget = settings.config.budget.model_copy(update={"cost_micro_usd": int(max_usd * 1e6)})
    return replace(settings, config=settings.config.model_copy(update={"budget": budget}))


async def main(city: str, pick: int, slot: str, max_usd: float) -> int:
    load_dotenv(".env", override=False)
    settings = capped(load_settings(), max_usd)
    container = build_container(settings)
    try:
        relational = container.relational
        if relational is None:
            print("no relational store configured")
            return 1
        candidates = await relational.reference.search_places(city)
        for n, c in enumerate(candidates):
            print(f"  [{n}] {c['name']}, {c['admin1_name']}, {c['country_name']}"
                  f" (pop {c['population']}, score {float(c['score']):.2f})")  # fmt: skip
        if not candidates:
            print("no place matched")
            return 1
        chosen = candidates[pick]
        print(f"researching [{pick}] {chosen['name']}, {chosen['country_name']} - slot {slot}")
        manager = RunManager(container, settings)
        started_at = time.monotonic()
        started = await manager.start(str(chosen["gazetteer_id"]), slots=[slot])
        await manager.wait(started.run_id)
        elapsed = time.monotonic() - started_at
        return await report(relational, started.run_id, elapsed)
    finally:
        await container.close()


async def report_only(run_id: str) -> int:
    load_dotenv(".env", override=False)
    container = build_container(load_settings())
    try:
        row = await container.relational.runs.run_row(run_id)  # type: ignore[union-attr]
        elapsed = (row["finished_at"] - row["started_at"]).total_seconds() if row else 0.0
        return await report(container.relational, run_id, elapsed)
    finally:
        await container.close()


async def report(relational: object, run_id: str, elapsed: float) -> int:
    engine = relational._engine  # type: ignore[attr-defined]
    events = await relational.runs.events_after(run_id, 0, limit=5000)  # type: ignore[attr-defined]
    types = Counter(e["type"] for e in events)
    finished = next(e["payload"] for e in events if e["type"] == "run_finished")
    print("\n== events ==")
    for e in events:
        p = e["payload"]
        if e["type"] == "crawl_decision":
            print(f"  gate   {p['outcome']:<24} {p['url']}  ({p['reason'][:90]})")
        elif e["type"] in ("source_fetched", "source_unreadable"):
            print(f"  {e['type']:<17} {p.get('url', '')} {p.get('parse_outcome', '')}")
        elif e["type"] == "claim_dropped":
            print(f"  dropped {p['reason']:<18} {p['statement'][:100]}\n"
                  f"          quote: {p.get('quote', '')[:160]!r}")  # fmt: skip
        elif e["type"] == "claim_verdict":
            print(f"  verdict {p['label']:<12} {p['claim_id']} by {p['verifier_model']}"
                  f"{' (fallback)' if p['fallback_used'] else ''}"
                  f" model said {p.get('model_label')}, issues {p.get('issues')}")  # fmt: skip
        elif e["type"] == "slot_planned":
            for q in p["queries"]:
                print(f"  query  [{q['lang']}] {q['text']}")
    async with engine.connect() as conn:
        facts_sql = text(
            "SELECT statement, quote, value_as_written, geography_level, geography_fit,"
            " label_spans, flags, url, verdict, rationale"
            " FROM v_fact_evidence WHERE run_id = :r ORDER BY status"
        )
        facts = (await conn.execute(facts_sql, {"r": run_id})).mappings().all()
        status_sql = text("SELECT status, count(*) FROM claim WHERE run_id = :r GROUP BY status")
        statuses = {k: v for k, v in (await conn.execute(status_sql, {"r": run_id})).all()}
    print("\n== claims ==")
    for f in facts:
        print(f"  [{f['verdict'] or 'unchecked'}] {f['statement']}\n"
              f"     quote: \"{f['quote']}\"\n     value: {f['value_as_written']}"
              f"  level: {f['geography_level']}  fit: {f['geography_fit']}\n"
              f"     label passages: {sorted(f['label_spans'])}  flags: {f['flags']}\n"
              f"     source: {f['url']}\n"
              f"     checker: {f['rationale']}")  # fmt: skip
    budget = finished["summary"]["budget"] if "summary" in finished else {}
    cost = budget.get("cost_micro_usd", 0) / 1e6
    print(f"\nstatus {finished['status']}; {elapsed:.0f} s; cost ${cost:.4f}; claims {statuses}")
    seqs = [e["seq"] for e in events]
    replay_ok = seqs == list(range(1, len(seqs) + 1))
    lines = [
        "# D2-3 thin slice: latest live run (counts only; no city data)",
        "",
        f"- status: {finished['status']}",
        f"- wall clock: {elapsed:.0f} s",
        f"- cost: ${cost:.4f} (model calls {budget.get('model_calls')}, "
        f"searches {budget.get('searches')}, fetches {budget.get('fetches')})",
        f"- events: {len(events)}; contiguous seq for replay: {replay_ok}",
        f"- event types: {dict(sorted(types.items()))}",
        f"- claims by status: {dict(sorted(statuses.items()))}",
        f"- by model: {budget.get('by_model')}",
    ]
    RESULTS.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"summary written to {RESULTS}")
    return 0 if statuses.get("supported", 0) >= 1 and replay_ok else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--city", default=os.environ.get("THIN_SLICE_CITY"))
    parser.add_argument("--pick", type=int, default=0)
    parser.add_argument("--slot", default="S04")
    parser.add_argument("--max-usd", type=float, default=0.5)
    parser.add_argument("--report", metavar="RUN_ID", help="report an existing run only")
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]  # queries in any script
    if args.report:
        sys.exit(asyncio.run(report_only(args.report)))
    if not args.city:
        parser.error("give --city (or THIN_SLICE_CITY); it is never saved")
    sys.exit(asyncio.run(main(args.city, args.pick, args.slot, args.max_usd)))
