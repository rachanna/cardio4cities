# S-6 full run (sparse-tuned): counts only, no city data

- status: stopped_by_budget; wall clock 425 s against the 420 s target
- model cost $1.148 of the $2.80 cap; Brave searches 32 (about $0.160); total about $1.308
- busy time per stage (ms, summed across parallel slots): {'fetch': 763279, 'wave0': 8172, 'search': 96206, 'writes': 3828, 'coverage': 547, 'planning': 14281, 'extraction': 564064, 'verification': 94873}
- cost and tokens per model: {'gpt-6.1-sol': {'calls': 16, 'tokens_in': 18231, 'tokens_out': 1931, 'cost_micro_usd': 55772}, 'claude-sonnet-5-5': {'calls': 1, 'tokens_in': 2014, 'tokens_out': 2050, 'cost_micro_usd': 24528}, 'claude-haiku-4-5-20251001': {'calls': 56, 'tokens_in': 818631, 'tokens_out': 49734, 'cost_micro_usd': 1067301}}
- slots by status: {'answered': 1, 'answered_negative': 10, 'answered_wider_geo': 5}
- claims by outcome: {'dropped': 100, 'refuted': 2, 'extracted': 13, 'supported': 11, 'insufficient': 9}
- dropped by reason: {'quote_length': 4, 'quote_not_found': 74, 'value_not_in_quote': 5, 'geography_elsewhere': 16, 'geography_unresolved': 1}
- certificate outcomes (crawl decisions by TLS cause, BD-15): {'expired': 3, 'issuer_missing': 1}
- re-plan rounds used: 0 across 0 slots
- sources: {'read': 27, 'blocked': {'blocked_login_or_paywall': 5}, 'unreadable': {'too_large': 1, 'unreadable': 4}, 'unreachable': {'unreachable_network': 15, 'unreachable_server_error': 2}}
- budget used: searches 32, fetches 55, robots 36, model calls 130, tokens in 838876 out 53715, refused ['wall_clock']
- budget warnings: [{'used': 51.0, 'limit': 60.0, 'counter': 'fetches'}, {'used': 361.7, 'limit': 420, 'counter': 'wall_clock'}]
- events: {'budget_warning': 2, 'claim_dropped': 100, 'claim_extracted': 129, 'claim_verdict': 16, 'crawl_decision': 77, 'fact_written': 5, 'identity_confirmed': 1, 'run_finished': 1, 'run_started': 1, 'search_done': 32, 'slot_planned': 16, 'slot_status': 16, 'source_fetched': 27, 'source_unreadable': 6, 'wave0_finding': 6}

| slot | status | flags | re-plans | queries | sources | best claims |
|---|---|---|---|---|---|---|
| S01 | answered_negative | - | 0 | 2 | 3 | 0 |
| S02 | answered_negative | - | 0 | 2 | 2 | 0 |
| S03 | answered_wider_geo | stale | 0 | 2 | 2 | 1 |
| S04 | answered_wider_geo | stale | 0 | 2 | 6 | 5 |
| S05 | answered_wider_geo | - | 0 | 2 | 4 | 1 |
| S06 | answered_wider_geo | - | 0 | 2 | 3 | 1 |
| S07 | answered_negative | - | 0 | 2 | 2 | 0 |
| S08 | answered_negative | - | 0 | 2 | 3 | 0 |
| S09 | answered_negative | - | 0 | 2 | 1 | 0 |
| S10 | answered_negative | - | 0 | 2 | 1 | 0 |
| S11 | answered | stale | 0 | 2 | 4 | 2 |
| S12 | answered_negative | - | 0 | 2 | 3 | 0 |
| S13 | answered_negative | - | 0 | 2 | 1 | 0 |
| S14 | answered_wider_geo | - | 0 | 2 | 1 | 1 |
| S15 | answered_negative | - | 0 | 2 | 1 | 0 |
| S16 | answered_negative | - | 0 | 2 | 3 | 0 |
