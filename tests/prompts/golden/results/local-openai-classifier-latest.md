# Prompt golden set: local-openai profile

- extractor gpt-6-luna; checker gpt-6.1-sol (low)
- prompt classifier: classifier@v2+11750b1c
- expected claims found: 0/0 (0%; bar 85%)
- expected fields correct: 0/0
- quotes located exactly: 0/0
- checker agreement: 0/0 (0%; bar 90%)
- trap claims mislabelled and then supported: 0
- planner problems: 0
- classifier cases passed: 10/11 (91%; bar 90%)
- answerer cases passed: 0/0 (0%; bar 90%); first-pass survival 0% (monitored: below 80% means revisit the prompt, LLD-5 §12.3)
- failed model calls: 0
- cost: $0.0014 in 11 calls
- **PASS**

## Classifier (classifier@v2+11750b1c)

- prevalence: ok
- control-rate: ok
- who-runs-public-health: ok
- leader: ok
- what-changed: type relationship, wanted one of ['change_over_time']
- as-of-date: ok
- out-of-scope: ok
- elliptical-follow-up: ok
- compound: ok
- acronym: ok
- injected-instruction: ok
