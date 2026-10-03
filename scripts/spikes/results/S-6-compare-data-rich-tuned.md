# S-6 before and after tuning (data-rich-tuned): counts only, no city data

| measure | before (BD-14) | after (BD-15) |
|---|---|---|
| status | stopped_by_budget | completed |
| wall clock (ledger) | 268 s | 177 s |
| model cost | $0.548 | $0.835 |
| Brave searches | 48 (about $0.240) | 32 (about $0.160) |
| total cost | $0.788 | $0.995 |
| tokens in / out | 385061 / 24361 | 605127 / 36120 |
| slots by status | {'answered': 2, 'unreachable': 3, 'answered_negative': 4, 'answered_wider_geo': 7} | {'answered': 2, 'unreachable': 2, 'answered_negative': 6, 'answered_wider_geo': 6} |
| claims by outcome | {'dropped': 2, 'refuted': 4, 'extracted': 1, 'supported': 15, 'insufficient': 2} | {'dropped': 24, 'refuted': 10, 'extracted': 7, 'supported': 13, 'insufficient': 6} |
| dropped by reason | {'geography_elsewhere': 1, 'geography_unresolved': 1} | {'quote_length': 2, 'quote_not_found': 10, 'value_not_in_quote': 7, 'geography_elsewhere': 5, 'geography_unresolved': 0} |
| sources | {'read': 29, 'blocked': {'blocked_login_or_paywall': 5}, 'unreadable': {'too_large': 1, 'unreadable': 4}, 'unreachable': {'unreachable_network': 13}} | {'read': 26, 'blocked': {'blocked_login_or_paywall': 7}, 'unreadable': {'unreadable': 7, 'unsupported_type': 1}, 'unreachable': {'unreachable_network': 16}} |
| certificate outcomes | not recorded | {'issuer_missing': 3} |
| re-plan rounds used | 0 | 0 |
| slots re-planned | 0 | 0 |
| fetches, robots, certificates | 56, 30, 0 | 60, 37, 3 |
| refused | ['wall_clock'] | [] |

| slot | before: status, re-plans, sources | after: status, re-plans, sources |
|---|---|---|
| S01 | answered_negative, 0, 4 | answered_negative, 0, 4 |
| S02 | answered_wider_geo, 0, 3 | answered_wider_geo, 0, 4 |
| S03 | answered_wider_geo, 0, 1 | answered_wider_geo, 0, 3 |
| S04 | answered_wider_geo, 0, 5 | answered_wider_geo, 0, 3 |
| S05 | answered_wider_geo, 0, 5 | answered_wider_geo, 0, 3 |
| S06 | answered_wider_geo, 0, 3 | answered_wider_geo, 0, 2 |
| S07 | answered_negative, 0, 3 | answered_negative, 0, 2 |
| S08 | answered_wider_geo, 0, 4 | answered_wider_geo, 0, 1 |
| S09 | unreachable, 0, 0 | unreachable, 0, 0 |
| S10 | answered, 0, 2 | unreachable, 0, 0 |
| S11 | unreachable, 0, 0 | answered, 0, 3 |
| S12 | answered_negative, 0, 4 | answered_negative, 0, 4 |
| S13 | answered, 0, 5 | answered, 0, 3 |
| S14 | answered_wider_geo, 0, 6 | answered_negative, 0, 1 |
| S15 | answered_negative, 0, 3 | answered_negative, 0, 2 |
| S16 | unreachable, 0, 0 | answered_negative, 0, 3 |
