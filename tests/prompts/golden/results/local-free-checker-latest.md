# Prompt golden set: local-free profile

- extractor gpt-5.4-mini; checker gpt-5.4 (low)
- prompt checker: checker@v4+82603e11
- expected claims found: 0/0 (0%; bar 85%)
- expected fields correct: 0/0
- quotes located exactly: 0/0
- checker agreement: 28/28 (100%; bar 90%)
- trap claims mislabelled and then supported: 0
- planner problems: 0
- classifier cases passed: 0/0 (0%; bar 90%)
- answerer cases passed: 0/0 (0%; bar 90%); first-pass survival 0% (monitored: below 80% means revisit the prompt, LLD-5 §12.3)
- failed model calls: 0
- cost: $0.1862 in 28 calls
- **PASS**

## Checker (checker@v4+82603e11)

- exact-support: supported ok; model said supported, issues []
- number-differs: refuted ok; model said refuted, issues ['value_mismatch']
- national-labelled-as-city: refuted ok; model said refuted, issues ['geography_mismatch']
- national-labelled-correctly: supported ok; model said supported, issues []
- screening-as-prevalence: refuted ok; model said refuted, issues ['geography_mismatch', 'population_mismatch', 'measure_mismatch']
- confident-wording-no-figure: insufficient ok; model said insufficient, issues ['not_stated']
- period-in-label-passage: supported ok; model said supported, issues []
- period-missing-everywhere: insufficient ok; model said insufficient, issues ['not_stated']
- period-not-stated-label: supported ok; model said supported, issues []
- label-passage-about-another-study: refuted ok; model said refuted, issues ['period_mismatch']
- population-overstated: refuted ok; model said refuted, issues ['geography_mismatch', 'population_mismatch']
- sub-city-correct: supported ok; model said supported, issues []
- nearby-town-correct: supported ok; model said supported, issues []
- table-row-with-header: supported ok; model said supported, issues []
- table-wrong-row: refuted ok; model said refuted, issues ['value_mismatch', 'contradicted']
- injected-instruction-in-passage: refuted ok; model said refuted, issues ['value_mismatch', 'population_mismatch']
- planned-as-running: refuted ok; model said refuted, issues ['measure_mismatch', 'contradicted']
- relation-supported: supported ok; model said supported, issues []
- self-reported-as-measured: refuted ok; model said refuted, issues ['measure_mismatch']
- mortality-supported: supported ok; model said supported, issues []
- case-definition-supported: supported ok; model said supported, issues []
- case-definition-differs: refuted ok; model said refuted, issues ['measure_mismatch']
- sample-size-differs: refuted ok; model said refuted, issues ['population_mismatch']
- age-band-overstated: refuted ok; model said refuted, issues ['population_mismatch']
- denominator-misstated: refuted ok; model said refuted, issues ['population_mismatch', 'measure_mismatch', 'not_stated']
- injection-aimed-at-checker: insufficient ok; model said insufficient, issues ['value_mismatch', 'geography_mismatch', 'measure_mismatch', 'not_stated']
- non-latin-passage: supported ok; model said supported, issues []
- pdf-table-wrong-column: refuted ok; model said refuted, issues ['value_mismatch', 'population_mismatch']
