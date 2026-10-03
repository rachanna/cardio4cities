# Spike S-5: PDF quote matching

Extractor stand-in: local Ollama `qwen2.5:3b` (pessimistic). Matching: LLD-2 §4.1, exact.

| Document | Segments (tables + numeric text) | Quotes | Matched | Dropped by reason |
|---|---|---|---|---|
| who_ncd_progress_monitor_2022 | 15 | 21 | 6 | quote_length 12, value_not_in_quote 3 |
| who_global_hypertension_report_2023 | 30 | 77 | 16 | quote_length 42, quote_not_found 9, value_not_in_quote 10 |

**Overall drop rate: 77.6%** of 98 quotes (pass bar: under about 20%).

## Run of 2026-10-03 (robots timeout 15 s; prose layout boxes no longer treated as tables)

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

**Decision needed (owner):** how short quotes from table rows may be, without risking a
short quote anchoring to the wrong row. Matching takes the first occurrence, so a short,
repeated string could attach a value to the wrong place: precision first.

**Status:** fails the bar as measured (77.6% dropped); the cause is identified.
