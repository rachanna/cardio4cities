# S-6 full run (sparse): counts only, no city data

- status: stopped_by_budget; wall clock 316 s against the 300 s target
- model cost $1.095 of the $5.00 cap; Brave searches 48 (about $0.240); total about $1.335
- busy time per stage (ms, summed across parallel slots): {'fetch': 578514, 'wave0': 20609, 'search': 666878, 'writes': 5108, 'coverage': 578, 'planning': 20641, 'extraction': 697187, 'verification': 213626}
- cost and tokens per model: {'gpt-6.1-sol': {'calls': 20, 'tokens_in': 21706, 'tokens_out': 2157, 'cost_micro_usd': 64982}, 'claude-sonnet-5-5': {'calls': 1, 'tokens_in': 1993, 'tokens_out': 3155, 'cost_micro_usd': 35536}, 'claude-haiku-4-5-20251001': {'calls': 61, 'tokens_in': 845331, 'tokens_out': 29869, 'cost_micro_usd': 994676}}
- slots by status: {'answered': 2, 'unreachable': 1, 'answered_negative': 7, 'answered_wider_geo': 6}
- claims by outcome: {'dropped': 44, 'refuted': 5, 'extracted': 11, 'supported': 12, 'insufficient': 9}
- dropped by reason: {'quote_not_found': 16, 'geography_elsewhere': 27, 'geography_unresolved': 1}
- sources: {'read': 29, 'blocked': {'blocked_login_or_paywall': 4}, 'unreadable': {'too_large': 1, 'unreadable': 7}, 'unreachable': {'unreachable_network': 15, 'unreachable_server_error': 2}}
- budget used: searches 48, fetches 54, robots 36, model calls 147, tokens in 869030 out 35181, refused ['wall_clock']
- budget warnings: [{'used': 41.0, 'limit': 48.0, 'counter': 'searches'}, {'used': 51.0, 'limit': 60.0, 'counter': 'fetches'}, {'used': 258.4, 'limit': 300, 'counter': 'wall_clock'}]
- events: {'budget_warning': 3, 'claim_dropped': 44, 'claim_extracted': 75, 'claim_verdict': 20, 'crawl_decision': 74, 'fact_written': 6, 'identity_confirmed': 1, 'run_finished': 1, 'run_started': 1, 'search_done': 48, 'slot_planned': 16, 'slot_status': 16, 'source_fetched': 29, 'source_unreadable': 9, 'wave0_finding': 6}

| slot | status | flags | re-plans | queries | sources | best claims |
|---|---|---|---|---|---|---|
| S01 | answered_negative | - | 0 | 3 | 4 | 0 |
| S02 | answered_negative | - | 0 | 3 | 2 | 0 |
| S03 | answered_wider_geo | stale | 0 | 3 | 4 | 1 |
| S04 | answered_wider_geo | stale | 0 | 3 | 5 | 4 |
| S05 | answered_wider_geo | - | 0 | 3 | 3 | 1 |
| S06 | answered_wider_geo | - | 0 | 3 | 5 | 1 |
| S07 | answered_negative | - | 0 | 3 | 3 | 0 |
| S08 | answered_negative | - | 0 | 3 | 2 | 0 |
| S09 | answered_negative | - | 0 | 3 | 1 | 0 |
| S10 | answered_negative | - | 0 | 3 | 2 | 0 |
| S11 | answered | stale | 0 | 3 | 3 | 1 |
| S12 | answered_wider_geo | stale | 0 | 3 | 5 | 1 |
| S13 | answered_negative | - | 0 | 3 | 1 | 0 |
| S14 | answered_wider_geo | - | 0 | 3 | 3 | 2 |
| S15 | answered | stale | 0 | 3 | 4 | 1 |
| S16 | unreachable | - | 0 | 3 | 0 | 0 |
