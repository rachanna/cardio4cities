# S-6 full run (fx12-before): counts only, no city data

- status: stopped_by_budget; wall clock 422 s against the 420 s target
- model cost $0.188 of the $0.37 cap; Brave searches 32 (about $0.160); total about $0.348
- busy time per stage (ms, summed across parallel slots): {'fetch': 1899266, 'wave0': 13219, 'search': 560202, 'writes': 69205, 'coverage': 1047, 'planning': 10094, 'extraction': 1178034, 'verification': 176000}
- cost and tokens per model: {'gpt-6-luna': {'calls': 73, 'tokens_in': 1154630, 'tokens_out': 56794, 'cost_micro_usd': 143860}, 'gpt-6.1-sol': {'calls': 10, 'tokens_in': 15742, 'tokens_out': 1281, 'cost_micro_usd': 44294}}
- slots by status: {'blocked': 1, 'answered': 3, 'answered_negative': 6, 'answered_wider_geo': 6}
- claims by outcome: {'dropped': 18, 'extracted': 4, 'supported': 14, 'insufficient': 2}
- dropped by reason: {'quote_not_found': 12, 'value_not_in_quote': 1, 'geography_elsewhere': 4, 'geography_not_stated': 1, 'geography_unresolved': 0}
- certificate outcomes (crawl decisions by TLS cause, BD-15): {'issuer_missing': 1}
- re-plan rounds used: 0 across 0 slots
- sources: {'read': 30, 'blocked': {'blocked_login_or_paywall': 4}, 'unreadable': {'unreadable': 4}, 'unreachable': {'unreachable_network': 4}}
- budget used: searches 32, fetches 51, robots 28, model calls 139, tokens in 1170372 out 58075, refused ['wall_clock']
- budget warnings: [{'used': 51.0, 'limit': 60.0, 'counter': 'fetches'}, {'used': 363.2, 'limit': 420, 'counter': 'wall_clock'}]
- events: {'budget_warning': 2, 'claim_dropped': 18, 'claim_extracted': 32, 'claim_verdict': 10, 'crawl_decision': 59, 'fact_written': 8, 'identity_confirmed': 1, 'run_finished': 1, 'run_started': 1, 'search_done': 32, 'slot_planned': 16, 'slot_status': 16, 'source_fetched': 30, 'source_unreadable': 5, 'step_failed': 24, 'wave0_finding': 6}

| slot | status | flags | re-plans | queries | sources | best claims |
|---|---|---|---|---|---|---|
| S01 | answered_negative | - | 0 | 2 | 3 | 0 |
| S02 | answered_wider_geo | stale | 0 | 2 | 3 | 1 |
| S03 | answered_wider_geo | stale | 0 | 2 | 4 | 2 |
| S04 | answered_wider_geo | stale | 0 | 2 | 5 | 3 |
| S05 | answered_wider_geo | - | 0 | 2 | 3 | 1 |
| S06 | answered_wider_geo | - | 0 | 2 | 2 | 1 |
| S07 | answered_negative | - | 0 | 2 | 2 | 0 |
| S08 | answered_negative | - | 0 | 2 | 2 | 0 |
| S09 | blocked | - | 0 | 2 | 0 | 0 |
| S10 | answered | - | 0 | 2 | 1 | 1 |
| S11 | answered | - | 0 | 2 | 1 | 3 |
| S12 | answered_negative | - | 0 | 2 | 3 | 0 |
| S13 | answered_wider_geo | - | 0 | 2 | 3 | 1 |
| S14 | answered_negative | - | 0 | 2 | 2 | 0 |
| S15 | answered_negative | - | 0 | 2 | 3 | 0 |
| S16 | answered | stale | 0 | 2 | 3 | 1 |
