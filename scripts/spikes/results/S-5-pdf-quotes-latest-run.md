# Spike S-5: PDF quote matching

Extractor: `claude-haiku-4-5-20251001`. Matching: LLD-2 §4.1, exact.

| Document | Segments (tables + numeric text) | Quotes | Matched | Dropped by reason |
|---|---|---|---|---|
| who_ncd_progress_monitor_2022 | 15 | 45 | 45 | none |
| who_global_hypertension_report_2023 | 30 | 79 | 43 | quote_length 13, quote_not_found 2, quote_not_unique 21 |

**Overall drop rate: 29.0%** of 124 quotes (pass bar: under about 20%).

Uniqueness scoped to the text the model was shown: **12.9%** dropped (matched 108, quote_length 13, quote_not_found 2, quote_not_unique 1).
