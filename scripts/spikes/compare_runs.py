"""Side-by-side S-6 runs (BD-15): the run before and after the owner's tuning, for one
city label. Reads the git-ignored details `full_run.py` saved in `spike_results/` and
writes counts only (no city data) to `scripts/spikes/results/`.

    uv run python -m scripts.spikes.compare_runs --old data-rich --new data-rich-tuned
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "spike_results"
RESULTS = Path(__file__).parent / "results"


def latest(label: str) -> dict[str, Any]:
    files = sorted(RAW_DIR.glob(f"S-6-{label}-run_*.json"), key=lambda f: f.stat().st_mtime)
    if not files:
        raise SystemExit(f"no saved run for label {label!r} in {RAW_DIR}")
    run: dict[str, Any] = json.loads(files[-1].read_text(encoding="utf-8"))
    return run


def facts(run: dict[str, Any]) -> dict[str, Any]:
    summary, slots = run["summary"], run["slots"]
    budget = summary.get("budget", {})
    searches = int(budget.get("searches", 0))
    model = float(summary.get("cost_usd", 0))
    return {
        "status": run.get("status")
        or ("stopped_by_budget" if budget.get("refused") else "completed"),
        "wall clock (ledger)": f"{summary['time']['wall_clock_ms'] / 1000:.0f} s",
        "model cost": f"${model:.3f}",
        "Brave searches": f"{searches} (about ${searches * 0.005:.3f})",
        "total cost": f"${model + searches * 0.005:.3f}",
        "tokens in / out": f"{budget.get('tokens_in')} / {budget.get('tokens_out')}",
        "slots by status": summary.get("slots"),
        "claims by outcome": summary.get("claims"),
        "dropped by reason": summary.get("dropped"),
        "sources": summary.get("sources"),
        "certificate outcomes": run.get("tls", "not recorded"),
        "re-plan rounds used": sum(s["replans_used"] for s in slots),
        "slots re-planned": sum(1 for s in slots if s["replans_used"]),
        "fetches, robots, certificates": f"{budget.get('fetches')}, {budget.get('robots')},"
        f" {budget.get('certificates', 0)}",
        "refused": budget.get("refused"),
    }


def main(old_label: str, new_label: str) -> int:
    old, new = latest(old_label), latest(new_label)
    a, b = facts(old), facts(new)
    lines = [
        f"# S-6 before and after tuning ({new_label}): counts only, no city data",
        "",
        "| measure | before (BD-14) | after (BD-15) |",
        "|---|---|---|",
        *(f"| {k} | {a[k]} | {b[k]} |" for k in a),
        "",
        "| slot | before: status, re-plans, sources | after: status, re-plans, sources |",
        "|---|---|---|",
    ]
    before = {s["slot_id"]: s for s in old["slots"]}
    for s in new["slots"]:
        o = before.get(s["slot_id"], {})
        lines.append(
            f"| {s['slot_id']} | {o.get('status')}, {o.get('replans_used')},"
            f" {len(o.get('sources_checked', []))} | {s['status']}, {s['replans_used']},"
            f" {len(s['sources_checked'])} |"
        )
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"S-6-compare-{new_label}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--old", required=True)
    parser.add_argument("--new", required=True)
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.exit(main(args.old, args.new))
