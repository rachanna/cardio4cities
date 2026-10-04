# Prompt golden set: local-openai profile

- extractor gpt-6-luna; checker gpt-6.1-sol (low)
- expected claims found: 32/37
- expected fields correct: 56/58
- quotes located exactly: 30/30
- checker agreement: 0/0 (0%; bar 90%)
- trap claims mislabelled and then supported: 0
- failed model calls: 0
- cost: $0.0229 in 35 calls
- **PASS**

## Extractor (extractor@v3+06a4232e)

- city-control-all-in-quote: all expected fields correct
- national-figure-in-city-newspaper: all expected fields correct
- study-by-city-authors-elsewhere: all expected fields correct
- screening-positivity: missing 22.7% (got [])
- range-up-to: all expected fields correct
- range-between: missing 20-25% (got ['between 20-25%'])
- planned-programme: all expected fields correct
- percentage-without-base: all expected fields correct
- injected-instruction: all expected fields correct
- confident-wording-no-figure: no claims, as expected
- table-row-with-period-in-methods: 22.6 (19.1-26.4): wrong period_year; missing 19.8 (16.0-24.1) (got ['22.6 (19.1-26.4)'])
- table-spanned-label-rows: all expected fields correct
- methods-period-far-from-figure: 29.3%: wrong period_year
- period-not-stated: all expected fields correct
- sub-city-population: all expected fields correct
- nearby-town: all expected fields correct
- province-figure: all expected fields correct
- self-reported-prevalence: all expected fields correct
- programme-output-count: all expected fields correct
- mortality-rate: all expected fields correct
- governs-relation: all expected fields correct
- leads-relation-dated: all expected fields correct
- modelled-estimate: all expected fields correct
- nine-areas-combined: all expected fields correct
- hypertension-awareness: all expected fields correct
- small-sample-setting: missing 52% (got [])
- translated-quote: all expected fields correct
- salt-policy-statement: all expected fields correct
- irrelevant-page: no claims, as expected
- denominator-all-adults: all expected fields correct
- sampling-not-described: all expected fields correct
- random-sample-with-size: all expected fields correct
- area-not-named: no claims, as expected
- cascade-denominator-not-subgroup: missing 41.5% (got [])
- clinic-patients-subgroup: all expected fields correct
