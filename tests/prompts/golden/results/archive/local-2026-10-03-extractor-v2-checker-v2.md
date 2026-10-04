# Prompt golden set: local profile

- extractor claude-haiku-4-5-20251001; checker gpt-6-luna (low)
- expected claims found: 29/32
- expected fields correct: 50/50
- quotes located exactly: 31/31
- checker agreement: 19/20 (95%; bar 90%)
- trap claims mislabelled and then supported: 0
- failed model calls: 0
- cost: $0.2030 in 51 calls
- **PASS**

## Extractor (extractor@v2+11c911ef)

- city-control-all-in-quote: all expected fields correct
- national-figure-in-city-newspaper: all expected fields correct
- study-by-city-authors-elsewhere: all expected fields correct
- screening-positivity: all expected fields correct
- range-up-to: all expected fields correct
- range-between: all expected fields correct
- planned-programme: all expected fields correct
- percentage-without-base: all expected fields correct
- injected-instruction: all expected fields correct
- confident-wording-no-figure: no claims, as expected
- table-row-with-period-in-methods: missing 19.8 (16.0-24.1)
- table-spanned-label-rows: all expected fields correct
- methods-period-far-from-figure: all expected fields correct
- period-not-stated: all expected fields correct
- sub-city-population: all expected fields correct
- nearby-town: all expected fields correct
- province-figure: all expected fields correct
- self-reported-prevalence: all expected fields correct
- programme-output-count: missing 48,300
- mortality-rate: missing 212 per 100,000
- governs-relation: all expected fields correct
- leads-relation-dated: all expected fields correct
- modelled-estimate: all expected fields correct
- nine-areas-combined: all expected fields correct
- hypertension-awareness: all expected fields correct
- small-sample-setting: all expected fields correct
- translated-quote: all expected fields correct
- salt-policy-statement: all expected fields correct
- irrelevant-page: no claims, as expected
- denominator-all-adults: all expected fields correct

## Checker (checker@v2+c8f63b03)

- exact-support: supported ok; model said supported, issues []
- number-differs: refuted ok; model said refuted, issues ['value_mismatch']
- national-labelled-as-city: refuted ok; model said refuted, issues ['geography_mismatch']
- national-labelled-correctly: supported ok; model said supported, issues []
- screening-as-prevalence: refuted ok; model said refuted, issues ['geography_mismatch', 'measure_mismatch']
- confident-wording-no-figure: insufficient ok; model said insufficient, issues ['not_stated']
- period-in-label-passage: insufficient MISMATCH (expected supported); model said insufficient, issues ['geography_mismatch']
- period-missing-everywhere: insufficient ok; model said insufficient, issues ['period_mismatch', 'measure_mismatch']
- period-not-stated-label: supported ok; model said supported, issues []
- label-passage-about-another-study: refuted ok; model said refuted, issues ['period_mismatch', 'geography_mismatch']
- population-overstated: refuted ok; model said refuted, issues ['geography_mismatch', 'population_mismatch']
- sub-city-correct: supported ok; model said supported, issues []
- nearby-town-correct: supported ok; model said supported, issues []
- table-row-with-header: supported ok; model said supported, issues []
- table-wrong-row: refuted ok; model said refuted, issues ['value_mismatch', 'geography_mismatch']
- injected-instruction-in-passage: refuted ok; model said refuted, issues ['value_mismatch', 'population_mismatch']
- planned-as-running: refuted ok; model said refuted, issues ['contradicted', 'period_mismatch']
- relation-supported: supported ok; model said supported, issues []
- self-reported-as-measured: refuted ok; model said refuted, issues ['measure_mismatch']
- mortality-supported: supported ok; model said supported, issues []
