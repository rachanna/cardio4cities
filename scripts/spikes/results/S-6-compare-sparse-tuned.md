# S-6 before and after tuning (sparse-tuned): counts only, no city data

| measure | before (BD-14) | after (BD-15) |
|---|---|---|
| status | stopped_by_budget | stopped_by_budget |
| wall clock (ledger) | 316 s | 425 s |
| model cost | $1.095 | $1.148 |
| Brave searches | 48 (about $0.240) | 32 (about $0.160) |
| total cost | $1.335 | $1.308 |
| tokens in / out | 869030 / 35181 | 838876 / 53715 |
| slots by status | {'answered': 2, 'unreachable': 1, 'answered_negative': 7, 'answered_wider_geo': 6} | {'answered': 1, 'answered_negative': 10, 'answered_wider_geo': 5} |
| claims by outcome | {'dropped': 44, 'refuted': 5, 'extracted': 11, 'supported': 12, 'insufficient': 9} | {'dropped': 100, 'refuted': 2, 'extracted': 13, 'supported': 11, 'insufficient': 9} |
| dropped by reason | {'quote_not_found': 16, 'geography_elsewhere': 27, 'geography_unresolved': 1} | {'quote_length': 4, 'quote_not_found': 74, 'value_not_in_quote': 5, 'geography_elsewhere': 16, 'geography_unresolved': 1} |
| sources | {'read': 29, 'blocked': {'blocked_login_or_paywall': 4}, 'unreadable': {'too_large': 1, 'unreadable': 7}, 'unreachable': {'unreachable_network': 15, 'unreachable_server_error': 2}} | {'read': 27, 'blocked': {'blocked_login_or_paywall': 5}, 'unreadable': {'too_large': 1, 'unreadable': 4}, 'unreachable': {'unreachable_network': 15, 'unreachable_server_error': 2}} |
| certificate outcomes | not recorded | {'expired': 3, 'issuer_missing': 1} |
| re-plan rounds used | 0 | 0 |
| slots re-planned | 0 | 0 |
| fetches, robots, certificates | 54, 36, 0 | 55, 36, 3 |
| refused | ['wall_clock'] | ['wall_clock'] |

| slot | before: status, re-plans, sources | after: status, re-plans, sources |
|---|---|---|
| S01 | answered_negative, 0, 4 | answered_negative, 0, 3 |
| S02 | answered_negative, 0, 2 | answered_negative, 0, 2 |
| S03 | answered_wider_geo, 0, 4 | answered_wider_geo, 0, 2 |
| S04 | answered_wider_geo, 0, 5 | answered_wider_geo, 0, 6 |
| S05 | answered_wider_geo, 0, 3 | answered_wider_geo, 0, 4 |
| S06 | answered_wider_geo, 0, 5 | answered_wider_geo, 0, 3 |
| S07 | answered_negative, 0, 3 | answered_negative, 0, 2 |
| S08 | answered_negative, 0, 2 | answered_negative, 0, 3 |
| S09 | answered_negative, 0, 1 | answered_negative, 0, 1 |
| S10 | answered_negative, 0, 2 | answered_negative, 0, 1 |
| S11 | answered, 0, 3 | answered, 0, 4 |
| S12 | answered_wider_geo, 0, 5 | answered_negative, 0, 3 |
| S13 | answered_negative, 0, 1 | answered_negative, 0, 1 |
| S14 | answered_wider_geo, 0, 3 | answered_wider_geo, 0, 1 |
| S15 | answered, 0, 4 | answered_negative, 0, 1 |
| S16 | unreachable, 0, 0 | answered_negative, 0, 3 |
