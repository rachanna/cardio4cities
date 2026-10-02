# Spike S-5: PDF quote matching — status: open (2026-10-03)

Script: `scripts/spikes/pdf_quotes.py` (`uv run poe spike pdf_quotes`). Documents: two global
WHO reports from WHO's IRIS repository, fetched through the real crawl gate and pinned fetcher.
Extractor stand-in: local Ollama `qwen2.5:3b` (no cost; pessimistic). Matching: LLD-2 §4.1, exact.

## What the runs showed

| Finding | Effect | Action |
|---|---|---|
| IRIS serves `robots.txt` in 7-10 s (`www.who.int`: 0.16 s), over LLD-2's 5 s robots timeout | With 5 s, IRIS is always recorded `unreachable_network` and nothing is fetched | Made `fetch.robots_timeout_s` a config key, still 5 s; raising it is an owner decision (BD-07) |
| A read timeout escaped the fetcher as a raw `httpcore` exception | Would have crashed a run instead of recording "unreachable" | Fixed: every httpcore error becomes `FetchError`; regression test added |
| One report's PDF is served as `application/octet-stream` | Recorded `unsupported_type` | Fixed: generic types are sniffed by the `%PDF-` signature only; tests added |
| On the progress monitor (2022), pdfplumber's table extraction turned layout boxes of prose into "tables" whose first row had 181 words | All 15 model quotes of such rows exceeded the 60-word quote limit (`quote_length`); none reached matching | Open: filter non-tabular "tables" (long prose cells) or split cells into lines, then re-run. Never loosen matching |
| IRIS then refused connections from this machine (likely rate limiting after repeated downloads) | The measurement could not be repeated | Re-run later, once, with the parsing fix |

## Not yet measured

The drop rate on genuine table rows. Pass bar: under about 20% of claims dropped.
Re-run with the production extractor once spend is approved.
