# S-6 full run (data-rich-tuned): counts only, no city data

- status: completed; wall clock 177 s against the 420 s target
- model cost $0.835 of the $3.00 cap; Brave searches 32 (about $0.160); total about $0.995
- busy time per stage (ms, summed across parallel slots): {'fetch': 625765, 'wave0': 11172, 'search': 95154, 'writes': 3249, 'coverage': 609, 'planning': 13422, 'extraction': 591078, 'verification': 195312}
- cost and tokens per model: {'gpt-6.1-sol': {'calls': 23, 'tokens_in': 24575, 'tokens_out': 2413, 'cost_micro_usd': 73280}, 'claude-sonnet-5-5': {'calls': 1, 'tokens_in': 2015, 'tokens_out': 2016, 'cost_micro_usd': 24190}, 'claude-haiku-4-5-20251001': {'calls': 44, 'tokens_in': 578537, 'tokens_out': 31691, 'cost_micro_usd': 736992}}
- slots by status: {'answered': 2, 'unreachable': 2, 'answered_negative': 6, 'answered_wider_geo': 6}
- claims by outcome: {'dropped': 24, 'refuted': 10, 'extracted': 7, 'supported': 13, 'insufficient': 6}
- dropped by reason: {'quote_length': 2, 'quote_not_found': 10, 'value_not_in_quote': 7, 'geography_elsewhere': 5, 'geography_unresolved': 0}
- certificate outcomes (crawl decisions by TLS cause, BD-15): {'issuer_missing': 3}
- re-plan rounds used: 0 across 0 slots
- sources: {'read': 26, 'blocked': {'blocked_login_or_paywall': 7}, 'unreadable': {'unreadable': 7, 'unsupported_type': 1}, 'unreachable': {'unreachable_network': 16}}
- budget used: searches 32, fetches 60, robots 37, model calls 130, tokens in 605127 out 36120, refused []
- budget warnings: [{'used': 51.0, 'limit': 60.0, 'counter': 'fetches'}]
- events: {'budget_warning': 1, 'claim_dropped': 24, 'claim_extracted': 54, 'claim_verdict': 23, 'crawl_decision': 83, 'fact_written': 7, 'identity_confirmed': 1, 'run_finished': 1, 'run_started': 1, 'search_done': 32, 'slot_planned': 16, 'slot_status': 16, 'source_fetched': 26, 'source_unreadable': 10, 'wave0_finding': 6}

| slot | status | flags | re-plans | queries | sources | best claims |
|---|---|---|---|---|---|---|
| S01 | answered_negative | - | 0 | 2 | 4 | 0 |
| S02 | answered_wider_geo | - | 0 | 2 | 4 | 1 |
| S03 | answered_wider_geo | stale | 0 | 2 | 3 | 1 |
| S04 | answered_wider_geo | stale | 0 | 2 | 3 | 3 |
| S05 | answered_wider_geo | - | 0 | 2 | 3 | 2 |
| S06 | answered_wider_geo | - | 0 | 2 | 2 | 1 |
| S07 | answered_negative | - | 0 | 2 | 2 | 0 |
| S08 | answered_wider_geo | stale | 0 | 2 | 1 | 2 |
| S09 | unreachable | - | 0 | 2 | 0 | 0 |
| S10 | unreachable | - | 0 | 2 | 0 | 0 |
| S11 | answered | - | 0 | 2 | 3 | 2 |
| S12 | answered_negative | - | 0 | 2 | 4 | 0 |
| S13 | answered | - | 0 | 2 | 3 | 1 |
| S14 | answered_negative | - | 0 | 2 | 1 | 0 |
| S15 | answered_negative | - | 0 | 2 | 2 | 0 |
| S16 | answered_negative | - | 0 | 2 | 3 | 0 |
