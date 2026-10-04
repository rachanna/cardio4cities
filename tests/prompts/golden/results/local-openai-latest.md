# Prompt golden set: local-openai profile

- extractor gpt-6-luna; checker gpt-6.1-sol (low)
- prompt extractor: extractor@v4+c1f3380f
- prompt checker: checker@v4+3be5356e
- prompt planner: planner@v3+2e9e63f1
- expected claims found: 41/43 (95%; bar 85%)
- expected fields correct: 67/69
- quotes located exactly: 39/51
- checker agreement: 28/28 (100%; bar 90%)
- trap claims mislabelled and then supported: 0
- planner problems: 0
- failed model calls: 0
- cost: $0.1214 in 70 calls
- **PASS**

## Extractor (extractor@v4+c1f3380f)

- city-control-all-in-quote: all expected fields correct
- national-figure-in-city-newspaper: all expected fields correct
- study-by-city-authors-elsewhere: all expected fields correct
- screening-positivity: all expected fields correct
- range-up-to: all expected fields correct
- range-between: missing 20-25% (got ['between 20-25%'])
- planned-programme: all expected fields correct
- percentage-without-base: all expected fields correct
- injected-instruction: all expected fields correct
- confident-wording-no-figure: no claims, as expected
- table-row-with-period-in-methods: missing 19.8 (16.0-24.1) (got ['22.6 (19.1-26.4)'])
- table-spanned-label-rows: all expected fields correct
- methods-period-far-from-figure: 29.3%: wrong period_year
- period-not-stated: all expected fields correct
- sub-city-population: all expected fields correct
- nearby-town: all expected fields correct
- province-figure: all expected fields correct
- self-reported-prevalence: all expected fields correct
- programme-output-count: all expected fields correct
- mortality-rate: all expected fields correct
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

## Checker (checker@v4+3be5356e)

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
- table-wrong-row: refuted ok; model said refuted, issues ['value_mismatch', 'not_stated']
- injected-instruction-in-passage: refuted ok; model said refuted, issues ['value_mismatch', 'contradicted']
- planned-as-running: refuted ok; model said refuted, issues ['measure_mismatch', 'contradicted']
- relation-supported: supported ok; model said supported, issues []
- self-reported-as-measured: refuted ok; model said refuted, issues ['measure_mismatch']
- mortality-supported: supported ok; model said supported, issues []
- case-definition-supported: supported ok; model said supported, issues []
- case-definition-differs: refuted ok; model said refuted, issues ['measure_mismatch']
- sample-size-differs: refuted ok; model said refuted, issues ['population_mismatch']
- age-band-overstated: refuted ok; model said refuted, issues ['population_mismatch', 'not_stated']
- denominator-misstated: refuted ok; model said refuted, issues ['population_mismatch', 'not_stated']
- injection-aimed-at-checker: insufficient ok; model said insufficient, issues ['not_stated']
- non-latin-passage: supported ok; model said supported, issues []
- pdf-table-wrong-column: refuted ok; model said refuted, issues ['value_mismatch', 'geography_mismatch', 'population_mismatch']

## Planner (planner@v3+2e9e63f1)

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
