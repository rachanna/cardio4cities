# D2-3 thin slice: latest live run (counts only; no city data)

- status: completed
- wall clock: 91 s
- cost: $0.0646 (model calls 8, searches 3, fetches 4)
- events: 45; contiguous seq for replay: True
- event types: {'claim_dropped': 10, 'claim_extracted': 18, 'claim_verdict': 3, 'crawl_decision': 4, 'fact_written': 1, 'identity_confirmed': 1, 'run_finished': 1, 'run_started': 1, 'search_done': 3, 'slot_planned': 1, 'source_fetched': 2}
- claims by status: {'extracted': 5, 'insufficient': 2, 'supported': 1}
- by model: {'gpt-6-luna': {'calls': 3, 'tokens_in': 2708, 'tokens_out': 435, 'cost_micro_usd': 489}, 'claude-haiku-4-5-20251001': {'calls': 3, 'tokens_in': 36103, 'tokens_out': 5607, 'cost_micro_usd': 64138}}
