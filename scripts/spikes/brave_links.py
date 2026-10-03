"""Spike S-4: Brave Search API, Search plan, links only (R-58, AT-33, BD-14).

Two live requests with a generic query that names no place (about $0.01 on the Search
plan, inside Brave's monthly free credit): one raw, to see every field Brave returns and
its rate-limit headers, and one through `BraveSearch`, to confirm the adapter keeps URL,
title and snippet only. The key comes from BRAVE_API_KEY in .env and is never printed.

Raw responses go to `spike_results/` (git-ignored: results may name real places); a
summary of field names and counts only goes to `scripts/spikes/results/`.

    uv run python -m scripts.spikes.brave_links
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

from app.adapters.search.brave import BRAVE_URL, LINKS_ONLY, BraveSearch

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "spike_results" / "S-4-brave-raw.json"
SUMMARY = Path(__file__).parent / "results" / "S-4-brave-links.md"
QUERY = "WHO STEPS survey hypertension control adults"  # generic: names no place
CONTENT_FIELDS = {"extra_snippets", "summary", "summarizer", "deep_results", "page_content"}
RATE_HEADERS = ("x-ratelimit-limit", "x-ratelimit-policy", "x-ratelimit-remaining",
                "x-ratelimit-reset")  # fmt: skip


def keys(obj: Any) -> list[str]:
    return sorted(obj) if isinstance(obj, dict) else []


async def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    key = os.environ.get("BRAVE_API_KEY", "")
    if not key:
        print("BRAVE_API_KEY is not set")
        return 1
    params = {"q": QUERY, "count": "10", "search_lang": "en", **LINKS_ONLY}
    headers = {"x-subscription-token": key, "accept": "application/json"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        response = await client.get(BRAVE_URL, params=params)
    print(f"raw request: HTTP {response.status_code}")
    response.raise_for_status()
    body = response.json()
    results = body.get("web", {}).get("results", [])
    result_keys = sorted({k for r in results for k in r})
    content_seen = sorted(
        {k for r in results for k in r if k in CONTENT_FIELDS} | (CONTENT_FIELDS & set(body))
    )
    rate = {h: response.headers.get(h) for h in RATE_HEADERS}

    await asyncio.sleep(1.1)  # the Search plan allows one request per second
    hits = await BraveSearch(key, rate_per_s=1).search(QUERY, "en", 10)
    hit_fields = sorted({f for h in hits for f in h.model_dump()})

    RAW.parent.mkdir(exist_ok=True)
    RAW.write_text(
        json.dumps({"params": params, "rate": rate, "body": body}, indent=2), encoding="utf-8"
    )
    lines = [
        "# S-4: Brave Search API, links only (field names and counts only)",
        "",
        f"- request parameters: {sorted(params)} with {LINKS_ONLY}",
        f"- top-level response fields: {keys(body)}",
        f"- `web` fields: {keys(body.get('web'))}",
        f"- web results: {len(results)}; fields per result: {result_keys}",
        f"- content fields present (should be none): {content_seen or 'none'}",
        f"- rate-limit headers: {rate}",
        f"- adapter hits: {len(hits)}; fields: {hit_fields}",
        "- cost: 2 requests on the Search plan (about $0.01, inside the monthly free credit)",
    ]
    SUMMARY.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    ok = results and not content_seen and hit_fields == ["rank", "snippet", "title", "url"]
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
