# S-6 full run (fx12-after): counts only, no city data

- status: completed; wall clock 360 s against the 420 s target
- model cost $0.172 of the $0.37 cap; Brave searches 32 (about $0.160); total about $0.332
- busy time per stage (ms, summed across parallel slots): {'fetch': 2081409, 'wave0': 7047, 'search': 490405, 'writes': 117641, 'coverage': 1828, 'planning': 11390, 'extraction': 621112, 'verification': 493050}
- cost and tokens per model: {'gpt-6-luna': {'calls': 65, 'tokens_in': 829072, 'tokens_out': 43839, 'cost_micro_usd': 104832}, 'gpt-6.1-sol': {'calls': 16, 'tokens_in': 24616, 'tokens_out': 1769, 'cost_micro_usd': 66922}}
- slots by status: {'blocked': 1, 'answered': 2, 'answered_negative': 6, 'answered_wider_geo': 7}
- claims by outcome: {'dropped': 7, 'extracted': 1, 'supported': 18, 'insufficient': 4}
- dropped by reason: {'quote_not_found': 2, 'geography_elsewhere': 4, 'geography_unresolved': 1}
- certificate outcomes (crawl decisions by TLS cause, BD-15): {'issuer_missing': 2}
- re-plan rounds used: 0 across 0 slots
- sources: {'read': 28, 'blocked': {'blocked_login_or_paywall': 6}, 'unreadable': {'too_large': 4, 'unreadable': 2}, 'unreachable': {'unreachable_network': 4, 'unreachable_server_error': 1}}
- budget used: searches 32, fetches 51, robots 37, model calls 127, tokens in 853688 out 45608, refused []
- budget warnings: [{'used': 51.0, 'limit': 60.0, 'counter': 'fetches'}, {'used': 357.2, 'limit': 420, 'counter': 'wall_clock'}]
- events: {'budget_warning': 2, 'claim_dropped': 7, 'claim_extracted': 24, 'claim_verdict': 16, 'crawl_decision': 62, 'fact_written': 12, 'identity_confirmed': 1, 'run_finished': 1, 'run_started': 1, 'search_done': 32, 'slot_planned': 16, 'slot_status': 16, 'source_fetched': 28, 'source_unreadable': 8, 'step_failed': 11, 'wave0_finding': 6}

| slot | status | flags | re-plans | queries | sources | best claims |
|---|---|---|---|---|---|---|
| S01 | answered_negative | - | 0 | 2 | 3 | 0 |
| S02 | answered_negative | - | 0 | 2 | 2 | 0 |
| S03 | answered_wider_geo | stale | 0 | 2 | 3 | 2 |
| S04 | answered_wider_geo | stale | 0 | 2 | 5 | 4 |
| S05 | answered_wider_geo | - | 0 | 2 | 4 | 2 |
| S06 | answered_wider_geo | - | 0 | 2 | 3 | 1 |
| S07 | answered_negative | - | 0 | 2 | 3 | 0 |
| S08 | answered_wider_geo | stale | 0 | 2 | 3 | 2 |
| S09 | answered_negative | - | 0 | 2 | 1 | 0 |
| S10 | answered | - | 0 | 2 | 3 | 1 |
| S11 | blocked | - | 0 | 2 | 0 | 0 |
| S12 | answered_negative | - | 0 | 2 | 5 | 0 |
| S13 | answered_wider_geo | - | 0 | 2 | 3 | 3 |
| S14 | answered_negative | - | 0 | 2 | 1 | 0 |
| S15 | answered_wider_geo | - | 0 | 2 | 3 | 2 |
| S16 | answered | stale | 0 | 2 | 1 | 1 |
