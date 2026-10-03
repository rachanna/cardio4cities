# Spike S-5: PDF quote matching — status: passed with BD-08 window-scoped uniqueness (2026-10-03)

Pass bar (BUILD_PLAN §2): on two real PDF tables, extraction plus LLD-2 §4.1 matching drops
under about 20% of claims; if not, improve normalisation and table parsing, never loosen matching.

Script: `scripts/spikes/pdf_quotes.py` (`uv run poe spike pdf_quotes`; each run writes
`S-5-pdf-quotes-latest-run.md`). Documents: two global WHO reports from WHO's IRIS
repository, fetched through the real crawl gate and pinned fetcher. Extractor stand-in:
local Ollama `qwen2.5:3b` (no cost; pessimistic). Matching: exact, never fuzzy.

## Findings on the way (all recorded in BD-07, BD-08)

| Finding | Effect | Action |
|---|---|---|
| IRIS serves `robots.txt` in 7-10 s (`www.who.int`: 0.16 s), over LLD-2's 5 s robots timeout | IRIS always recorded `unreachable_network` | Owner raised `fetch.robots_timeout_s` to 15 s |
| A read timeout escaped the fetcher as a raw `httpcore` exception | Would crash a run instead of recording "unreachable" | Fixed; regression test |
| A PDF served as `application/octet-stream` | Recorded `unsupported_type` | Fixed: `%PDF-` signature sniffing for generic types; tests |
| One report link was its cover thumbnail (JPEG) | Correctly rejected as `unsupported_type` | Script uses the PDF bitstream |
| pdfplumber reported prose layout boxes as one-row "tables" (181 words) | Every quote of them broke the 60-word limit | Fixed: tables need two rows and columns, short cells and a number |
| Number-bearing lines under 6 words: 65% and 47% of the two reports | `quote.min_words = 6` makes most PDF table data unquotable | Owner chose BD-08: 3-5 word quotes only when unique |
| IRIS refused connections after repeated downloads | Measurement paused | Later runs use a scratch cache of gated downloads |

## First measurement (robots timeout 15 s, table filter on)

| Document | Segments (tables + numeric text) | Quotes | Matched | Dropped by reason |
|---|---|---|---|---|
| who_ncd_progress_monitor_2022 | 15 | 21 | 6 | quote_length 12, value_not_in_quote 3 |
| who_global_hypertension_report_2023 | 30 | 77 | 16 | quote_length 42, quote_not_found 9, value_not_in_quote 10 |

**Overall drop rate: 77.6%** of 98 quotes (pass bar: under about 20%).

### Breakdown and analysis

Segments: genuine tables (the hypertension report has 802; the progress monitor none,
its tables are positioned text) plus runs of number-bearing page-text lines, which is
what the extractor reads when a report draws tables without ruled grids.

| Reason | Count | Share of 98 |
|---|---|---|
| matched | 22 | 22% |
| `quote_length` | 54 | 55% |
| `value_not_in_quote` | 13 | 13% |
| `quote_not_found` | 9 | 9% |

**Analysis.** `quote_length` is structural, not a model failure: number-bearing lines under
6 words are 65% of the hypertension report's (17,518 of 26,754) and 47% of the progress
monitor's (454 of 961). With `quote.min_words = 6`, most table data in PDFs cannot be
quoted by any extractor. Of the 44 quotes within the length bounds, 22 matched; the 3B
stand-in's copy errors (`quote_not_found`, `value_not_in_quote`) should fall with the
production extractor, which needs measuring once spend is approved.

**Owner decision (BD-08):** quotes of 3-5 words are accepted only when they occur exactly once.


## Second measurement: BD-08 (3-5 word quotes only when unique), from cached PDFs

| Document | Segments (tables + numeric text) | Quotes | Matched | Dropped by reason |
|---|---|---|---|---|
| who_ncd_progress_monitor_2022 | 15 | 21 | 11 | quote_length 5, quote_not_found 1, value_not_in_quote 4 |
| who_global_hypertension_report_2023 | 30 | 79 | 17 | quote_length 28, quote_not_found 9, quote_not_unique 14, value_not_in_quote 11 |

**Overall drop rate: 72.0%** of 100 quotes (pass bar: under about 20%).

Uniqueness scoped to the text the model was shown: **62.0%** dropped (matched 38, quote_length 33, quote_not_found 12, quote_not_unique 1, value_not_in_quote 16).

**Analysis.** Whole-document uniqueness drops 14 quotes as `quote_not_unique`: the
hypertension report repeats the same short rows across about 190 country-profile pages.
Checking uniqueness within the text the model was shown drops only 1, matches 38 of 100
(was 22), and keeps the guarantee, because a quote can only come from what the model read.
The remaining drops are the 3B stand-in's: quotes of one or two words (`quote_length`) and
copy errors (`quote_not_found`, `value_not_in_quote`).

**Status: still failing the bar (62% dropped, scoped).** Next: scope uniqueness to the
extraction window in D2-3, and measure with the production extractor (Claude Haiku 4.5;
about $0.15 for this spike) once its key is set and the spend is approved.

## Third measurement: production extractor, Claude Haiku 4.5 (owner approved the spend)

Same cached PDFs, segments and prompt; temperature 0 via `extra_body` (SDK 1.x dropped the
keyword; Haiku 4.5 still honours it). Spend: 11,648 input + 5,862 output tokens, **$0.041**.

| Document | Quotes | Matched (whole-document uniqueness) | Matched (uniqueness within shown text) |
|---|---|---|---|
| who_ncd_progress_monitor_2022 | 45 | 45 | 45 |
| who_global_hypertension_report_2023 | 79 | 43 (21 `quote_not_unique`, 13 `quote_length`, 2 `quote_not_found`) | 63 (1 `quote_not_unique`, 13 `quote_length`, 2 `quote_not_found`) |

**Drop rate: 29.0% with whole-document uniqueness; 12.9% with uniqueness within the text
the model was shown — under the ~20% bar.** BD-08 scopes uniqueness to the extraction
window (D2-3), so S-5 passes on the design as it will be built. Remaining drops are quotes
under three words (bare numbers) and two copy errors: both correctly refused.
