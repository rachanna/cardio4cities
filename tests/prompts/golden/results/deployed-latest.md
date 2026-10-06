# Prompt golden set: deployed profile

- extractor claude-haiku-4-5-20251001; checker gpt-6.1-sol (low)
- prompt extractor: extractor@v6+0f19b998
- prompt checker: checker@v4+82603e11
- prompt planner: planner@v4+cfc4e1e2
- prompt classifier: classifier@v2+11750b1c
- prompt answerer: answerer@v2+5f18d06d
- expected claims found: 43/48 (90%; bar 85%)
- expected fields correct: 67/69
- quotes located exactly: 46/46
- checker agreement: 28/28 (100%; bar 90%)
- trap claims mislabelled and then supported: 0
- planner problems: 0
- classifier cases passed: 10/11 (91%; bar 90%)
- answerer cases passed: 9/9 (100%; bar 90%); first-pass survival 100% (monitored: below 80% means revisit the prompt, LLD-5 §12.3)
- failed model calls: 0
- cost: $0.2883 in 99 calls
- **PASS**

## Extractor (extractor@v6+0f19b998)

- city-control-all-in-quote: all expected fields correct
- national-figure-in-city-newspaper: all expected fields correct
- study-by-city-authors-elsewhere: all expected fields correct
- screening-positivity: all expected fields correct
- range-up-to: all expected fields correct
- range-between: missing 20-25% (got ['between 20-25%'])
- planned-programme: all expected fields correct
- percentage-without-base: 35%: wrong denominator_stated; trap mislabelled; checker said refuted
- injected-instruction: all expected fields correct
- confident-wording-no-figure: no claims, as expected
- table-row-with-period-in-methods: missing 22.6 (19.1-26.4) (got ['22.6']); missing 19.8 (16.0-24.1) (got ['22.6'])
- table-spanned-label-rows: all expected fields correct
- methods-period-far-from-figure: all expected fields correct
- period-not-stated: all expected fields correct
- sub-city-population: all expected fields correct
- nearby-town: all expected fields correct
- province-figure: all expected fields correct
- self-reported-prevalence: all expected fields correct
- programme-output-count: missing 48,300 (got ['statement'])
- mortality-rate: missing 212 per 100,000 (got ['212 per 100,000 population'])
- governs-relation: Coastal District Office: wrong relation_type
- leads-relation-dated: all expected fields correct
- modelled-estimate: all expected fields correct
- nine-areas-combined: all expected fields correct
- hypertension-awareness: all expected fields correct
- small-sample-setting: all expected fields correct
- translated-quote: all expected fields correct
- salt-policy-statement: all expected fields correct
- irrelevant-page: no claims, as expected
- denominator-all-adults: all expected fields correct
- sampling-not-described: all expected fields correct
- random-sample-with-size: all expected fields correct
- area-not-named: no claims, as expected
- cascade-denominator-not-subgroup: all expected fields correct
- clinic-patients-subgroup: all expected fields correct
- pdf-table-no-separators: all expected fields correct
- inline-reference-markers: all expected fields correct
- area-only-in-context: no claims, as expected
- case-definition-in-methods: all expected fields correct
- european-sample-size: all expected fields correct
- many-figures-one-window: all expected fields correct
- undiagnosed-is-not-awareness: all expected fields correct
- prevalence-method-not-stated: all expected fields correct
- table-value-without-unit: all expected fields correct
- borough-is-part-of-the-city: all expected fields correct

## Checker (checker@v4+82603e11)

- exact-support: supported ok; model said supported, issues []
- number-differs: refuted ok; model said refuted, issues ['value_mismatch']
- national-labelled-as-city: refuted ok; model said refuted, issues ['geography_mismatch']
- national-labelled-correctly: supported ok; model said supported, issues []
- screening-as-prevalence: refuted ok; model said refuted, issues ['geography_mismatch', 'measure_mismatch']
- confident-wording-no-figure: insufficient ok; model said insufficient, issues ['not_stated']
- period-in-label-passage: supported ok; model said supported, issues []
- period-missing-everywhere: insufficient ok; model said insufficient, issues ['not_stated']
- period-not-stated-label: supported ok; model said supported, issues []
- label-passage-about-another-study: refuted ok; model said refuted, issues ['period_mismatch']
- population-overstated: refuted ok; model said refuted, issues ['geography_mismatch', 'population_mismatch']
- sub-city-correct: supported ok; model said supported, issues []
- nearby-town-correct: supported ok; model said supported, issues []
- table-row-with-header: supported ok; model said supported, issues []
- table-wrong-row: refuted ok; model said refuted, issues ['value_mismatch', 'geography_mismatch', 'not_stated']
- injected-instruction-in-passage: refuted ok; model said refuted, issues ['value_mismatch']
- planned-as-running: refuted ok; model said refuted, issues ['measure_mismatch', 'contradicted']
- relation-supported: supported ok; model said supported, issues []
- self-reported-as-measured: refuted ok; model said refuted, issues ['measure_mismatch']
- mortality-supported: supported ok; model said supported, issues []
- case-definition-supported: supported ok; model said supported, issues []
- case-definition-differs: refuted ok; model said refuted, issues ['measure_mismatch']
- sample-size-differs: refuted ok; model said refuted, issues ['population_mismatch']
- age-band-overstated: refuted ok; model said refuted, issues ['population_mismatch', 'not_stated']
- denominator-misstated: refuted ok; model said refuted, issues ['population_mismatch', 'measure_mismatch', 'not_stated']
- injection-aimed-at-checker: insufficient ok; model said insufficient, issues ['not_stated']
- non-latin-passage: supported ok; model said supported, issues []
- pdf-table-wrong-column: refuted ok; model said refuted, issues ['value_mismatch', 'geography_mismatch', 'population_mismatch']

## Planner (planner@v4+cfc4e1e2)

- S01: ok
- S02: ok
- S03: ok
- S04: ok
- S05: ok
- S06: ok
- S07: ok
- S08: ok
- S09: ok
- S10: ok
- S11: ok
- S12: ok
- S13: ok
- S14: ok
- S15: ok
- S16: ok

## Classifier (classifier@v2+11750b1c)

- prevalence: ok
- control-rate: ok
- who-runs-public-health: ok
- leader: ok
- what-changed: ok
- as-of-date: type figure, wanted one of ['relationship', 'change_over_time']; slots ['S12'] lack ['S01']
- out-of-scope: ok
- elliptical-follow-up: ok
- compound: ok
- acronym: ok
- injected-instruction: ok

## Answerer (answerer@v2+5f18d06d)

- city-figure: ok; post-check removed 0, repaired 0
- national-only: ok; post-check removed 0, repaired 0
- sources-disagree: ok; post-check removed 0, repaired 0
- no-leader-found: ok; post-check removed 0, repaired 0
- outdated-figure: ok; post-check removed 0, repaired 0
- who-runs: ok; post-check removed 0, repaired 0
- only-a-mention: ok; post-check removed 0, repaired 0
- injected-mention: ok; post-check removed 0, repaired 0
- compound-with-a-gap: ok; post-check removed 0, repaired 0
