# Coverage and usefulness: recommendations

**For:** the owner, to decide what to change before the prompts and models are frozen (first rehearsal, D4-6), and what goes in the deck as the roadmap.
**Status:** proposed, 2026-10-05. Nothing here is built. Each item that is approved gets a BD row when it is built.

---

## 1. Summary

The system is built for precision: a wrong or misattributed fact is a failure, and an honest "not found" is a correct answer. The price is coverage. In spike S-6, a sparse city had only 2 of its 16 questions answered at city level. Most of the rest were answered with state or national figures, badged "Not city-level", or not found.

Those numbers predate several coverage fixes (BD-15, BD-16), so **current coverage is unknown**. The recommendation is to measure first, then make two changes that keep every precision rule intact.

| # | Recommendation | When | Effort | Spend |
|---|---|---|---|---|
| R1 | **Measure coverage** on the deployed system: 2 or 3 cities | First, after deployment | One afternoon | About $3 to $9, plus Brave |
| R2 | **Read academic papers through Europe PMC's official API** | Before the freeze | About half a day | None to build; tested with recorded responses |
| R3 | **Make wider-area results read as useful findings** ("Best available: state figure") | Before the freeze | About 2 hours | None |
| R4 | **Present gaps as findings** for a City Lead | Before the freeze | About 1 hour, mostly wording | None |
| R5 | Steer the planner to reports and PDFs (a prompt change) | Only if R1 shows weak source discovery | About 2 hours plus a golden-set run | About $1 for the run |
| R6 | Tune the budget settings (config only) | Only if R1 shows runs stopping early | Minutes plus a measuring run | About $3 a run |
| R7 to R10 | Deep mode, local languages, document upload, more official sources | After the demo: roadmap slide | Days each | — |

**Guardrails.** No recommendation loosens quote matching, accepts a weak verdict, hides the "Not city-level" badge or bypasses a block (§6).

---

## 2. What we know

### Spike S-6 (D2-5, before BD-15 and BD-16)

Two full live runs with the deployed models and Brave search:

| | Data-rich city | Sparse city |
|---|---|---|
| Run time | 268 s | 316 s |
| Model cost | $0.55 | $1.10 |
| Slots answered at city level | 2 | 2 |
| Slots answered with wider-area data | 7 | 6 |
| Slots not found | 4 | 7 |
| Slots unreachable | 3 | 1 |
| Claims confirmed | 15 | 12 |
| Claims dropped by the precision rules | — | 44 (27 about other places) |

Both runs ended "stopped by budget". **No re-plan round ever ran:** the first round used all 48 searches.

### Fixed since S-6 (unmeasured)

| Fix | Decision | Expected effect |
|---|---|---|
| Searches raised from 48 to 64; 2 queries per slot instead of 3 | BD-15 | Round 1 uses 32 searches, so weak slots get a second round |
| Priority slots re-planned first (S04, S03, S05, S06) | BD-15 | The questions that matter most get the extra searches |
| Government sites with incomplete certificate chains are completed safely | BD-15, BD-16 | National and state health sites stop being "unreachable" |
| Pages about other places ranked lower | BD-15 | Fewer wasted extractions |
| City figures checked and shown before national ones | BD-36 | The best geography reaches the checker first |
| Search rate raised from 1 to 5 a second | BD-15 | Less time waiting on search |

---

## 3. Where coverage is lost

| Loss | Cause | Can we recover it? |
|---|---|---|
| **The data does not exist online at city level** | Many cities publish no city-level prevalence survey | No, and the system says so. This is a finding, not a failure (R4) |
| **Sources cannot be read** | CAPTCHAs, blocks, broken certificates, paywalls | Partly: an official API path where one exists (R2). Never by bypassing a block |
| **Claims fail a precision check** | Wrong place, quote not found exactly, checker refutes or finds the evidence insufficient | Partly, by better sources (R2, R5). Never by loosening the checks |
| **The budget runs out** | Time or search limits reached before weak slots get another round | Partly fixed (BD-15); measure (R1), then tune (R6) |
| **Found but hard to use** | A slot answered with a state figure looks empty to a reader | Yes, by presentation (R3) |

---

## 4. Recommendations before the freeze

### R1. Measure coverage on the deployed system

**What.** Run 2 or 3 cities on the deployed URL: one data-rich, one sparse, and the planned fallback city. Choose them on the day, never in the repository.

**Record for each run:**
- slots by status;
- claims confirmed, refuted, insufficient and dropped (by reason);
- sources blocked or unreachable (by reason);
- whether a re-plan round ran;
- run time and cost.

Everything comes from the run summary (`brief_ready`).

**Why first.** The S-6 numbers predate six fixes. Without new numbers, R5 and R6 would be guesses.

**Cost.** Each run is capped at $3; S-6 measured $0.55 to $1.10 in model cost per run, plus up to 64 Brave searches. The owner approves the cap.

**Done when.** A BD row records the per-run numbers next to S-6's.

### R2. Academic papers through Europe PMC's official API

**What.** Add Europe PMC as an approved official source. Links that search returns for Europe PMC or PubMed Central articles are read through Europe PMC's REST API (open-access full text) instead of the web pages, which now show a reCAPTCHA (BD-10). This was planned as D2-5 Phase 3 and not built.

**Why.**
- City-level prevalence and risk-factor studies are mostly published in journals.
- They are currently lost, because the system rightly refuses to bypass the CAPTCHA.
- It is an official API with published terms, so it fits the crawl-gate rules.

**How:**
- **Spike first:** confirm the API's terms of use, rate limit and the open-access full-text endpoint.
- **New adapter:** `app/adapters/structured/` (or a fetch-path adapter) behind the existing structured-data port. It records an `api_terms:europepmc` decision, as Wave 0 does, and goes through the same address checks and budget reservation as every other call.
- **Same pipeline:** the article text then goes through the normal pipeline (snapshot, exact quote matching, independent checker). Only the transport changes.
- **Tests:** recorded responses with fictional Halden Bay content. No live calls in tests.

**Risk.** Low. Only open-access articles can be read; others stay "unreachable", as now.

**Done when.**
- A slot whose best source is a PubMed Central link reads it through the API.
- The evidence panel shows the API snapshot.
- A BD row is written.

### R3. Make wider-area results read as useful findings

**What.** When a slot's best evidence is a state or national figure, the brief, the coverage grid and the report lead with it:

> **Best available: state figure, `<year>`.** `<value as written>` … *(Not city-level)*

Today such a slot shows its badge and gap note. A reader can take it as empty.

**Why.**
- In S-6, 6 to 7 of 16 slots were in this state.
- These figures are confirmed, sourced and correctly labelled. They are useful context for a City Lead, as long as they never pass for city data.

**How.**
- **Code:** presentation only, in the web app's slot and summary views and the report's dimension sections.
- **Rules unchanged:** the badge stays as the main badge. The order of facts stays as BD-36 sets it (city first). Nothing is stored differently.

**Guardrail.** The words "city", or the city's name, never label a wider-area figure (non-negotiable 8). The test asserts the badge and the label together.

**Done when.**
- The browser smoke test and AT-13 still pass.
- A new test checks the label wording against the badge.

### R4. Present gaps as findings

**What.** In the brief, the report's "What was not found" section and the deck, frame each gap by what it means for a City Lead:

> *No city-level hypertension survey was found (6 searches, 5 sources checked). A baseline survey would be a first step for CARDIO4Cities here.*

**How.**
- Wording in the gap-note templates (`app/workflow/rules/gap_notes.py`) and the report section intro.
- The "first step" sentence is fixed text chosen by slot type. It is never generated from the gap, and never states a fact.

**Why.** For a programme deciding where to start, knowing what does not exist is as useful as what does. It also turns the demo's most likely weakness into a point in the system's favour.

**Done when.** Gap-note tests are updated, and a decision row records the template wording.

---

## 5. Conditional (after R1's numbers)

### R5. Steer the planner to reports and PDFs

**Trigger.** R1 shows that sources were found but were mostly news or secondary pages, while primary documents were missed.

**What.** Planner prompt v5:
- prefer queries that find primary documents: annual health reports, survey reports, budget documents, PDFs;
- keep using `site:` filters for the country's government domains (already allowed, BD-14).

**Cost.**
- A prompt change needs the planner golden set re-run (about $1).
- It must be done before the freeze (LLD-3 §11.1 has the same timing).

### R6. Tune the budget settings

**Trigger.** R1 shows that runs stop before re-plan rounds, or that slots end with allowed sources never read.

**Settings** (all in `config/deployed.yaml`, so no code changes):

| Setting | Now | Option | Trade-off |
|---|---|---|---|
| `budget.wall_clock_s` | 420 | 480 | About 1 more minute per run in the demo |
| `budget.fetches` | 60 | 80 | More pages read; more time |
| `select.max_new_urls_per_slot_round` | 3 | 4 | More candidate sources per slot |
| `extract.max_windows_per_source` | 4 | 6 | Long PDFs read further; more extractor cost |
| `verify.max_claims_per_slot` | 5 | 7 | More claims checked; more checker cost |

**Rules for changing them:**
- Change one or two at a time.
- Measure again with one run.
- Keep the run inside the time agreed for the live demo.
- The per-run cost cap ($3) does not change without the owner.

---

## 6. What we will not do

Each of these would raise the coverage numbers and break a guarantee in the brief or the design:

| Do not | Why |
|---|---|
| Loosen quote matching (fuzzy matching) | A quote that is not in the source is a fabrication (LLD-2 §4.1) |
| Accept the checker's "supported, with issues" as supported | PD-03: any issue means insufficient |
| Show a national or state figure as a city figure, or drop its badge | Non-negotiable 8 |
| Bypass a CAPTCHA, login, paywall or block | Crawl gate rules; R-03 |
| Let models produce or correct numbers | Code parses `value_as_written` (LLD-2 §4.2) |
| Seed city data in code, prompts, config or fixtures | Non-negotiable 1 |

Claims that were reported but not confirmed already appear on their own, labelled "Reported, not confirmed", when a slot has fewer than three confirmed facts (`retrieval.mentions_only_if_facts_below`). That is the right way to show more without asserting more.

---

## 7. Roadmap after the demo (for the deck)

| # | Item | Value | Why not now |
|---|---|---|---|
| R7 | **Deep mode:** a background run of 15 to 20 minutes with a larger budget, enriching the quick brief | The largest coverage gain for real use | Too slow for a live demo |
| R8 | **Local-language search** (for example, regional languages in Indian cities) | Many municipal and state sources are not in English | Scoped out for the PoC (BD-31); needs per-language query and quote handling |
| R9 | **Document upload:** a City Lead adds a PDF they hold, processed by the same gate, quote matching and checker | Unlocks internal and offline reports | A new feature beyond the design |
| R10 | **More official structured sources**, such as national surveys with district-level tables | Real sub-city statistics, verified by code like Wave 0 | Needs per-country registries and their terms checked |
| — | **A re-ranking model** for retrieval, a feedback loop from City Leads, human review of contested facts | Quality at scale | Production concerns |

---

## 8. Decisions for the owner

1. **Approve R1** and set a cap for the measuring runs (suggested: $9 for 3 runs, plus Brave).
2. **Approve R2**: a small spike on Europe PMC's terms, then the adapter.
3. **Approve R3 and R4**: presentation and wording only.
4. **After R1:** decide on R5 and R6 from the numbers.
5. **Confirm the freeze order:**
   1. R1;
   2. R2 to R4;
   3. R5 and R6 if needed;
   4. LLD-3 §11.1 (classifier);
   5. golden runs (D4-1);
   6. freeze;
   7. rehearsals.
