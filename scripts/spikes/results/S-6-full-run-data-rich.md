# S-6 full run (data-rich): counts only, no city data

- status: stopped_by_budget; wall clock 268 s against the 300 s target
- model cost $0.548 of the $5.00 cap; Brave searches 48 (about $0.240); total about $0.788
- busy time per stage (ms, summed across parallel slots): {'fetch': 344343, 'wave0': 22625, 'search': 677861, 'writes': 12235, 'coverage': 593, 'planning': 20640, 'extraction': 331625, 'verification': 112673}
- cost and tokens per model: {'gpt-6.1-sol': {'calls': 15, 'tokens_in': 15862, 'tokens_out': 1660, 'cost_micro_usd': 48324}, 'claude-sonnet-5-5': {'calls': 1, 'tokens_in': 1994, 'tokens_out': 3053, 'cost_micro_usd': 34518}, 'claude-haiku-4-5-20251001': {'calls': 42, 'tokens_in': 367205, 'tokens_out': 19648, 'cost_micro_usd': 465445}}
- slots by status: {'answered': 2, 'unreachable': 3, 'answered_negative': 4, 'answered_wider_geo': 7}
- claims by outcome: {'dropped': 2, 'refuted': 4, 'extracted': 1, 'supported': 15, 'insufficient': 2}
- dropped by reason: {'geography_elsewhere': 1, 'geography_unresolved': 1}
- sources: {'read': 29, 'blocked': {'blocked_login_or_paywall': 5}, 'unreadable': {'too_large': 1, 'unreadable': 4}, 'unreachable': {'unreachable_network': 13}}
- budget used: searches 48, fetches 56, robots 30, model calls 134, tokens in 385061 out 24361, refused ['wall_clock']
- budget warnings: [{'used': 41.0, 'limit': 48.0, 'counter': 'searches'}, {'used': 51.0, 'limit': 60.0, 'counter': 'fetches'}, {'used': 267.4, 'limit': 300, 'counter': 'wall_clock'}]
- events: {'budget_warning': 3, 'claim_dropped': 2, 'claim_extracted': 18, 'claim_verdict': 15, 'crawl_decision': 77, 'fact_written': 9, 'identity_confirmed': 1, 'run_finished': 1, 'run_started': 1, 'search_done': 48, 'slot_planned': 16, 'slot_status': 16, 'source_fetched': 29, 'source_unreadable': 6, 'wave0_finding': 6}

| slot | status | flags | re-plans | queries | sources | best claims |
|---|---|---|---|---|---|---|
| S01 | answered_negative | - | 0 | 3 | 4 | 0 |
| S02 | answered_wider_geo | - | 0 | 3 | 3 | 1 |
| S03 | answered_wider_geo | stale | 0 | 3 | 1 | 1 |
| S04 | answered_wider_geo | stale | 0 | 3 | 5 | 7 |
| S05 | answered_wider_geo | - | 0 | 3 | 5 | 1 |
| S06 | answered_wider_geo | - | 0 | 3 | 3 | 1 |
| S07 | answered_negative | - | 0 | 3 | 3 | 0 |
| S08 | answered_wider_geo | - | 0 | 3 | 4 | 1 |
| S09 | unreachable | - | 0 | 3 | 0 | 0 |
| S10 | answered | stale | 0 | 3 | 2 | 1 |
| S11 | unreachable | - | 0 | 3 | 0 | 0 |
| S12 | answered_negative | - | 0 | 3 | 4 | 0 |
| S13 | answered | - | 0 | 3 | 5 | 1 |
| S14 | answered_wider_geo | - | 0 | 3 | 6 | 1 |
| S15 | answered_negative | - | 0 | 3 | 3 | 0 |
| S16 | unreachable | - | 0 | 3 | 0 | 0 |
