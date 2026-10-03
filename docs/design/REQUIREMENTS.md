# CARDIO4Cities City Intelligence: Requirements Specification

| | |
|---|---|
| **Version** | 1.3 |
| **Date** | 2026-10-02 |
| **Status** | Baselined. Changes need a decision-log entry. |
| **Source of truth** | Case-study brief: *CARDIO4Cities AI Engineer Case Study* (Full Stack Data Scientist) |
| **Location** | `docs/design/REQUIREMENTS.md` |
| **Feeds** | `docs/design/HLD.md` → `docs/design/LLD.md` → `docs/design/REPO_STRUCTURE.md` → `docs/design/BUILD_PLAN.md` → `CLAUDE.md` |
| **Companions** | `docs/design/BRAINSTORM.md` (reasoning behind the v1.1 additions) · `docs/DECISIONS.md` |

---

## 0. How to use this document

**Purpose.** This is the single list of what the system must do and how each requirement is verified. It contains no architecture. Design documents answer *how*; this document answers *what* and *how we prove it*.

**For Claude Code (implementation rules).**
1. A **MUST** requirement is not negotiable. Never weaken, skip or stub one without a decision-log entry (`docs/DECISIONS.md`) approved by the owner.
2. Every acceptance test in §13 (AT-xx) becomes an automated test under `tests/acceptance/` unless marked *demo-only*.
3. If an implementation choice changes a requirement's meaning, update this file in the same change.
4. When a requirement and a design document disagree, this file wins until the conflict is resolved in `docs/DECISIONS.md`.
5. Vendor SDKs (model providers, search APIs, database clients) are imported only inside the adapters layer (R-81). Workflow and domain code never call a vendor directly.

**ID families (stable, never reused; retire rather than renumber).**

| Prefix | Meaning |
|---|---|
| `R-xx` | Requirement (R-01 to R-28 come directly from the brief; R-29 and above are derived) |
| `C1`–`C5` | The five capabilities in the brief's problem statement |
| `CR-xx` | Content requirement (what "understanding a city" must cover) |
| `DQ-xx` | The brief's twelve open design questions |
| `DS-x` | The brief's seven demonstration steps |
| `AT-xx` | Acceptance test |
| `T-xx` | Data-quality hazard ("trap") the system must handle |
| `CON-xx` | Constraint |
| `A-xx` / `Q-xx` | Assumption / open question |

**Origin tags.** `[STATED]` the brief says it · `[INFERRED]` follows from the brief or from evidence gathered in analysis · `[ASSUMED]` working assumption, carries an A-xx and a check.

**Priority.** `MUST` (required for the submission to pass) · `SHOULD` (expected for a strong submission) · `COULD` (if time allows) · `WON'T` (deliberately out of scope for the PoC, see §17).

**Verification method.** `T` automated test · `D` shown in the live demo · `I` inspection of code, config or docs · `A` analysis or argument in the architecture document.

---

## 1. Problem context

### 1.1 Background `[STATED]`
CARDIO4Cities works with city governments to reduce cardiovascular disease by improving prevention, early diagnosis, treatment and long-term management of hypertension, type 2 diabetes and dyslipidaemia. The programme is expanding to many more cities. Before a City Lead meets government decision-makers and healthcare leaders in a new city, the team must understand that city. Today this is manual research across government websites, public reports, academic publications, health statistics, policy documents and stakeholder networks. The result is fragmented, hard to verify and not reusable across teams.

### 1.2 Problem statement
- **Business framing.** Give a City Lead, on demand, a trustworthy understanding of a city they have never researched, so they can walk into a first meeting with officials and not be caught out.
- **System framing.** Given only a city name at request time, run permission-gated live research on the public web, turn what is found into a structured, reusable knowledge asset in which every fact carries its evidence, verify claims independently, and serve that knowledge through exploration, question answering and a downloadable report that states what is not known.

### 1.3 What the brief is really testing `[INFERRED]`
Gathering information is easy for an LLM and is not what is graded. Six of the nine non-negotiables concern **trust and structure**: permission before crawling, an independent fact-checker, a knowledge graph, multiple stores, evidence on every fact, and no fabrication. The real question is whether a non-technical person can repeat the system's output to a government official without being embarrassed.

### 1.4 Design stance (binding on all design) `[INFERRED]`
1. **Precision over coverage.** A fabricated or misattributed fact is a failure. An honest "not found" is a correct output.
2. **Sparse is normal.** Analysis probes (Barcelona and Kumasi in this workspace; Bengaluru and Gadag in prior work) show that most target cities have **no city-level cardiovascular data**, only national or district figures and non-representative local studies. The system must be as convincing when it reports a gap as when it reports a finding.
3. **Abstention is a designed outcome**, not an error path.

---

## 2. Users

| ID | User | Need | Origin |
|---|---|---|---|
| U-01 | **City Lead** (primary) | A short, defensible brief before a first stakeholder meeting; plain-language follow-up answers; knowing what not to say | `[STATED]` role; non-technical `[ASSUMED A-01]` |
| U-02 | Programme and implementation teams | Reuse the asset at later visits and later playbook steps (for example, target setting uses the same care-cascade evidence) | `[INFERRED]` from "reusable intelligence asset" |
| U-03 | Reviewer or analyst | Inspect contested and low-confidence items after the fact | `[INFERRED]` |
| U-04 | Evaluation panel (demo audience) | Probe the system adversarially: unknown city, click-to-source, planted claims, trade-offs | `[STATED]` demonstration scenario |

**Why the stakes are high** `[INFERRED]`: the City Lead may restate the system's facts to powerful people. A wrong number, a departed official named as current, or a planned programme described as running damages the programme's credibility more than an admitted gap.

**How fast information goes stale** `[INFERRED]` (drives freshness labelling, R-30, and temporal storage, R-44):

| Information | Typical staleness | Decay |
|---|---|---|
| Named office-holders | months to 2 years | high |
| Programme status (running, piloting, ended) | months to years | medium-high |
| Policies and guidelines | document persists, status shifts | medium |
| Organisations' existence | years | low (their leadership: high) |
| Epidemiological figures | survey cadence, often 3–5+ years | low frequency, often stale on publication |
| Population and boundaries | census cadence | low |

---

## 3. Content scope: what "understanding a city" must cover

The brief lists six things a City Lead must understand. Two further areas are derived because the first six cannot be answered reliably without them. The dimension model used in design (HLD) must map every dimension back to these CR IDs.

Health scope `[STATED]`: hypertension, type 2 diabetes, dyslipidaemia; outcomes include stroke and heart attack. The **care cascade** (prevalence, screened, diagnosed, treated, controlled) is the programme's own success measure, and the **blood-pressure control rate** is the headline indicator `[INFERRED from cardio4cities.org]`.

| ID | Area | Minimum useful answer for a first meeting | Honest "not found" looks like | Origin |
|---|---|---|---|---|
| CR-01 | Cardiovascular health landscape | Headline figures for the three risk factors and the cascade (especially control), each with value, geography level, population, year and source | "No city-level figure found. National figure X (year, source) shown and flagged as national." | `[STATED]` |
| CR-02 | Existing healthcare programmes | Current CVD/NCD programmes with sponsor, where they operate, and status | "No programme confirmed to operate in the city. National or other-region programmes listed and flagged." | `[STATED]` |
| CR-03 | Major policy initiatives | Policies, plans and targets that apply, with level (city, state, national) and status | "No city-specific policy found; national policy applies (flagged)." | `[STATED]` |
| CR-04 | Stakeholders and organisations | Institutions and roles; named people only with current, corroborated evidence | "Institutions identified; current office-holders not verified from public sources." | `[STATED]` |
| CR-05 | Opportunities, risks and gaps | A few points, labelled as interpretation and linked to the facts they derive from | "Limited basis: only national data available." | `[STATED]` |
| CR-06 | Evidence supporting key findings | Not a topic: the evidence layer under CR-01 to CR-05 (see R-07) | n/a | `[STATED]`; reading `[INFERRED]` |
| CR-07 | City identity and governance baseline | Canonical place (country, administrative hierarchy), who runs public health today, recent reorganisations | "Governing body uncertain; sources disagree (both shown)." | `[INFERRED]`: needed to tag geography and avoid naming defunct bodies |
| CR-08 | Data and digital availability | What health data is published at city level or below, and in what form | "No city-level health data publication found." | `[INFERRED]`: the "Data & digital" pillar of the CARDIO approach |

**Depth rule** `[INFERRED]`: "enough for a first meeting", not a literature review. A handful of verified headline facts per area beats exhaustive coverage.

### 3.1 Research slots: the unit of work `[decided, v1.1]`
Each content area is broken into fixed **slots**: questions a program can mark as answered or not. The slot is the unit of work for planning, parallel research, the sufficiency check, the coverage grid, report sections and gap records (R-79). The catalogue is generic and contains no city facts.

| Dimension | Maps to | Slots |
|---|---|---|
| D1 Governance | CR-07, CR-04 | S01 Body that runs public health today · S02 Recent reorganisation of that body |
| D2 Burden | CR-01 | S03 Hypertension prevalence · **S04 Hypertension control rate (headline)** · S05 Diabetes prevalence · S06 Cardiovascular or stroke mortality |
| D3 Programmes | CR-02 | S07 NCD or hypertension programmes operating in the city · S08 Primary-care screening for these conditions |
| D4 Policy | CR-03 | S09 National NCD plan and targets · S10 Hypertension treatment protocol · S11 Tobacco or salt policy |
| D5 Stakeholders | CR-04 | S12 Health authority leadership · S13 Major hospitals and academic bodies · S14 NGOs and implementation partners |
| D6 Data | CR-08 | S15 City-level health data publication · S16 Health information system in use |

CR-05 (opportunities, risks and gaps) is derived from slot results. CR-06 (evidence) applies to every slot.

**Slot statuses.** At the end of every run, each slot has exactly one status:

| Status | Meaning |
|---|---|
| `answered` | At least one confirmed claim at the requested geography |
| `answered_wider_geo` | Only national, state, district or metro evidence, or evidence from a place within `geography.nearby_km` of the city (BD-10: surrounding populations depend on the city's services); shown flagged. Figures from farther places, or whose area cannot be placed, never answer |
| `answered_negative` | Searched; nothing acceptable found; queries and sources recorded |
| `blocked` | Every candidate source refused by the crawl gate |
| `unreachable` | Candidate sources could not be reached (network, geo-restriction, server error) |

Additional reason flags on a slot: `conflicting`, `stale`.

---

## 4. Capabilities (C1–C5) `[STATED]`

| ID | Capability | How a user notices it working | How it is faked or done badly | Realised by |
|---|---|---|---|---|
| C1 | Gather and organise information from public sources | Type a city, get an organised dossier, not a chat transcript | Pre-built cache; one aggregator page; unstructured text | R-01, R-10, R-11, R-12 |
| C2 | Create a reusable intelligence asset | A colleague opens the same city tomorrow and it is there, explorable, with dates | Text dump with no entities; report file with no structure; duplicate entities | R-05, R-06, R-12, R-43, R-44, R-45 |
| C3 | Help users explore and understand | Ask "who runs hypertension screening here?" and get a grounded answer; click through entities | Keyword search box; answers with no synthesis | R-14, R-15, R-29 |
| C4 | Communicate the evidence behind insights | Click any fact to see source, exact passage, date and geography | Bibliography at the end, not tied to claims; citation that does not contain the figure | R-07, R-45, R-55, R-56 |
| C5 | Identify uncertainty, missing information and data-quality issues | Visible "not found", "national figure", "sources disagree" markers | Never says "unknown"; cosmetic confidence score | R-08, R-16, R-33, R-47, R-48, R-52 |

---

## 5. Non-negotiables (R-01 to R-09)

`[STATED]` *"Everything else in this document is open to interpretation. This section is not. Each item is mandatory. How you implement it is entirely your decision."* All nine are **MUST**.

### R-01 Live internet research at request time
**Brief:** The system must research the public internet at request time. The panel may name a city during the demonstration. Pre-seeded or hard-coded city data does not qualify.

**Interpretation.** Nothing describing a specific city may exist in the system before a request for that city.
- **Allowed** (generic, describes no city's health): a world gazetteer for disambiguation; country-to-language mapping; a source-type registry keyed by country pattern or source type (for example "national statistics office", "WHO STEPS survey", "national health ministry"); indicator definitions; prompts that contain no city facts. `[ASSUMED A-09]`
- **Not allowed:** any city-specific figure, URL list, stakeholder, programme or example output loaded before the request; demo prompts or few-shot examples naming candidate demo cities.
- **Reuse:** a previously researched city may be reopened from storage only through an explicit "Open existing" action, with the run date shown. **"Research" always runs fresh live research**, even for a city researched before (R-83). `[decided, v1.1]`

**Acceptance criteria.**
1. A run for an unseen city performs outbound fetches after the request time, logged with timestamps.
2. No runtime path (prompts, config, fixtures, seed scripts) contains city-specific facts or per-city URL lists.
3. Works for a city in any country, including a data-sparse or non-English one.

**Fails if:** results arrive suspiciously fast for an unseen city; works only for a few cities; prompts contain city facts.
**Verification:** T (AT-01, AT-02), D (DS-1). **Related:** R-10, R-57.

### R-02 Orchestrated agentic workflow (LangGraph or comparable), walkable
**Interpretation.** A real graph of distinct, single-responsibility nodes with explicit shared state, conditional edges and bounded loops, generated from code so that the diagram cannot drift from the implementation.

**Acceptance criteria.**
1. The compiled workflow can be rendered as a diagram from code.
2. It has conditional routing at least for: crawl decision, fact-check verdict, and research sufficiency.
3. A run produces a trace in which each step maps to a named node, and shared state is inspectable between steps.

**Fails if:** one large prompt, a linear script, or a diagram drawn by hand that does not match the code.
**Verification:** T (AT-03), D (DS-2). **Related:** R-36, R-37, R-61, R-71.

### R-03 Crawlability detection agent, before anything is crawled
**Interpretation.** A distinct workflow step that decides, for every URL, whether automated extraction is permitted **before** any content is fetched, and whose decision is enforced.
- **Covers:** robots.txt rules (including crawl-delay), site terms of use that prohibit scraping, paywalls and login walls, and rate-limit signals (HTTP 429, `Retry-After`).
- **Applies to every fetch**, including fetches done by third-party tools or APIs on our behalf. Search results are used for URL discovery only (R-58).
- **May be mostly deterministic.** It is an agent in the workflow sense (autonomous decision with consequences). An LLM may assist only with ambiguous terms-of-use text.
- **Standards followed** `[v1.1]`: RFC 9309 including its error handling (robots.txt returning a 4xx error: crawling allowed; 5xx or unreachable: treat the whole site as disallowed `[check exact wording when implementing]`); `Content-Usage` opt-outs such as `ai=n` or `tdm=n` (IETF AI-preferences drafts) honoured as blocks; an honest user-agent string naming the project (R-86).
- **Search providers in links-only mode** `[v1.1]`: search APIs able to fetch page content themselves are configured so they never do (R-58).

**Acceptance criteria.**
1. For a disallowed URL, zero content requests reach that URL.
2. Each decision is logged: URL, allow / block / unreachable, reason, rule matched.
3. A block has a consequence: the workflow reroutes to another source or records the gap.
4. Crawl-delay and rate limits are honoured.

**Fails if:** fetch then check; robots ignored; crawling laundered through a scraping vendor; a block that changes nothing.
**Verification:** T (AT-04, AT-05, AT-06), D (DS-3). **Related:** R-40, R-58, R-59, R-68.

### R-04 Independent fact-checking agent, with consequences
**Interpretation.** A separate agent that judges each claim against its evidence without access to the producing agent's reasoning, can conclude *supported*, *refuted* or *insufficient*, and whose verdict changes what the system stores and shows.

**Acceptance criteria.**
1. The checker's input is restricted to the claim, its labels and the source passage located by code. It never receives the extractor's prompt, reasoning or conversation (R-38).
2. Three-way verdict: supported / refuted / insufficient.
3. **Consequences:** refuted and insufficient claims are never written to the graph, never shown as facts, and are recorded with the reason; the gap they leave is visible; the workflow may re-research the affected area within budget.
4. Every verdict records the model and prompt version used (R-62).

**Fails if:** the producer checks its own work; every claim passes; a failed claim still appears as fact.
**Verification:** T (AT-07, AT-08), D (DS-3). **Related:** R-38, R-47, R-56, R-69.

### R-05 Knowledge graph built with Graphiti, genuinely used at query time
**Interpretation.** Graphiti specifically (not a substitute), holding entities, typed relationships and time-bounded facts, with at least one user-facing question type that is answered by graph traversal or temporal query and that degrades if the graph is bypassed.

**Acceptance criteria.**
1. The graph is built with the Graphiti library.
2. At least one question class (relationships across people, organisations, programmes, policies; or "what was true at time T / what changed") is answered from the graph.
3. Disabling the graph for that class measurably degrades or prevents the answer.

**Fails if:** the graph is written but never read; answers come only from vector search or the LLM; a different graph library is used.
**Verification:** T (AT-10, AT-11), D (DS-5). **Related:** R-44, R-53, R-70.

### R-06 At least three datastores: relational, vector and graph
**Interpretation.** Three distinct engines, each on a real read path, with a written justification of what lives where and why. Additional stores (for example raw snapshots) are allowed.

**Acceptance criteria.**
1. Relational, vector and graph stores are separate engines.
2. Each store is read by at least one user-facing path.
3. The architecture document states, per store, what it owns and what would break without it.

**Fails if:** a store is populated but never read; a vector extension inside the relational database is presented as the separate vector store.
**Verification:** T (AT-11), I, A. **Related:** R-45, R-55.

### R-07 Evidence on every fact
**Interpretation.** For every fact the user sees, "where did this come from?" returns a real answer containing: source title and URL, publisher, publication date, retrieval date, the **verbatim supporting passage**, the geography level, and the verification verdict. Derived statements cite their inputs and method; interpretation is labelled as interpretation.

**Acceptance criteria.**
1. Every fact in answers, the report and the explorer resolves to the fields above.
2. Every quote was located verbatim in the fetched source by code (R-56).
3. The fetched source is preserved so the evidence can be shown even if the live page changes (R-55).

**Fails if:** a bibliography not tied to claims; a citation that does not contain the figure; a dead or invented URL.
**Verification:** T (AT-09, AT-12, AT-27), D (DS-6). **Related:** R-13, R-45, R-55, R-56.

### R-08 No fabrication; never present national data as city data without flagging it
**Interpretation.** Never invent statistics, people or attitudes. Generalise the national-as-city rule to **every mismatch** between what a figure describes and what the user asked about:
- **Geography** (national, state, district or metro area presented as the city);
- **Population** (adults only, a sub-group, patients, screened volunteers presented as everyone);
- **Time** (an old figure presented as current);
- **Measure** (screening positivity or programme output presented as prevalence).

**Acceptance criteria.**
1. Every figure carries geography level, population, reference period and measure type (R-33).
2. A figure that does not match the city or population asked about is shown with a visible flag in answers, the report and the explorer.
3. A question with no supporting evidence gets an abstention, not a guess. No person is named without evidence.

**Fails if:** a national figure shown as the city's; an invented stakeholder; a 2014 survey shown as current without its year.
**Verification:** T (AT-13, AT-14, AT-15, AT-21), D (DS-6). **Related:** R-16, R-33, R-63, R-64.

### R-09 Deployed and reachable at a URL
**Interpretation.** The panel opens a URL from their own network and uses the system live, including researching a city they name. Access control (for example an access code supplied to the panel) is acceptable `[ASSUMED A-12]`.

**Acceptance criteria.**
1. Public HTTPS URL, reachable from outside the developer's network.
2. A new-city run can be started and completes (or streams progress and partial results) within the demo tolerance (R-49).
3. Available throughout the evaluation window; a fallback exists if live research stalls (R-51).

**Fails if:** localhost, a recorded video, or a URL that cannot run an unseen city in demo time.
**Verification:** T (AT-17), D (DS-1). **Related:** R-49, R-50, R-51.

---

## 6. Functional requirements (R-10 to R-17) `[STATED]`, all MUST

| ID | Requirement | Acceptance criteria | Live or prepared | Verify |
|---|---|---|---|---|
| R-10 | Research a previously unseen city | Arbitrary city name starts a live run that completes or streams results within tolerance | Live | T AT-01, AT-16; D DS-1 |
| R-11 | Collect information from external sources | Fetches from several real public sources, all permission-gated | Live | T AT-04; D DS-3 |
| R-12 | Organise findings into a structured form | Findings land categorised by content area (§3) and in the stores; reopenable later | Live output, schema prepared | T AT-25; I |
| R-13 | Preserve references to supporting evidence | Each stored fact carries its source, passage, dates and geography | Live | T AT-12 |
| R-14 | Support exploration and discovery | Navigable brief plus entity / relationship exploration and filtering | Live UI; may be shown on an already researched city | D DS-4 |
| R-15 | Answer questions about the researched city | Grounded answers with citations from stored knowledge | Live | T AT-10, AT-28; D DS-5 |
| R-16 | Surface uncertainty and gaps rather than inventing | Explicit not-found, flagged, conflicting and low-confidence markers | Live, must be visible | T AT-13, AT-16; D DS-1, DS-6 |
| R-17 | Produce a downloadable research report | Download (PDF, plus Markdown or HTML) with citations, flags and a gaps section | Generated live; one pre-generated copy kept | T AT-18; D |

---

## 7. Derived requirements (R-29 and above) `[INFERRED]`

Derived from the brief, the panel review, and evidence gathered during analysis. IDs R-29 to R-54 are unchanged from earlier analysis; R-55 and above are new in this version.

### 7.1 Product and user experience

| ID | Requirement | Priority | Traces to | Verify |
|---|---|---|---|---|
| R-29 | A meeting-ready **executive summary** view: the few headline facts per content area, before detail | MUST | C3, R-27, U-01 | D DS-4 |
| R-30 | **Plain-language confidence and freshness labels** ("city-level, 2023", "national, flagged", "not found"); never a bare number; one main badge per fact (R-78) | MUST | R-08, R-16 | D |
| R-31 | A **"handle with care"** callout listing items the City Lead should not state without local verification | SHOULD | R-08, U-01 | D |
| R-32 | Report export readable by a non-technical audience (R-17) | SHOULD | R-17, R-27 | I |
| R-52 | **Graceful, visible degradation** on a sparse or awkward city: the gaps view is a designed screen, not an empty state | MUST | R-16, DS-1 | T AT-16; D |
| R-76 | From an answer that hits a gap, the user can request research on that gap (runs through the build path, never inline) | COULD | C3, R-63 | D |

### 7.2 Data, metadata and knowledge

| ID | Requirement | Priority | Traces to | Verify |
|---|---|---|---|---|
| R-33 | **Metric metadata on every quantitative fact**: value as written, unit, geography level and name, population (age, sex, group, sample size), case definition or threshold, method (measured or self-reported), measure type, denominator and whether stated, reference period, representativeness, source tier | MUST | R-08, T-01–T-04, T-07, T-09 | T AT-14, AT-21 |
| R-34 | **Explicit care-cascade model** per risk factor; each step with its own denominator and source; no chaining of percentages across sources | SHOULD | CR-01, T-09 | T AT-21 |
| R-35 | **Comparability rule**: figures are compared or reconciled only when their metadata is compatible; otherwise shown side by side with the difference explained | MUST | T-02, R-65 | T AT-20 |
| R-43 | **Entity resolution**: one real-world entity is one node across sources and runs | MUST | C2, R-05 | T AT-26 |
| R-44 | **Temporal facts**: facts carry validity in time; re-runs append, they do not overwrite; superseded facts are end-dated, not deleted | MUST | DQ-07, R-05 | T AT-10 |
| R-45 | **Cross-store provenance spine**: every graph element, vector chunk and relational row references canonical source and claim IDs, so provenance resolves whichever store answered | MUST | R-07, R-06 | T AT-12 |
| R-55 | **Raw snapshot preservation**: every fetched source stored as fetched bytes with a content hash and retrieval time | SHOULD | R-07, DS-6 | T AT-27 |
| R-57 | **City identity resolution before research**: canonical place with country and administrative hierarchy; ambiguous names (same name, different places) are disambiguated or the chosen identity is shown | MUST | R-01, T-16 | T AT-24 |
| R-60 | **Institutional churn**: renamed, merged, dissolved or replaced bodies are represented with time validity and are never shown as current once superseded | SHOULD | CR-07, T-13 | T AT-10 |
| R-70 | Stakeholder structure analytics on the graph (for example who is most connected) | COULD | CR-04, R-05 | D |

### 7.3 Agents and orchestration

| ID | Requirement | Priority | Traces to | Verify |
|---|---|---|---|---|
| R-36 | **Model-versus-code boundary**: anything checkable in code is enforced in code (permission, quote location, geography tags, conflict ordering, confidence, stopping, citation checks); models handle judgment only, and every model output is schema-validated before it affects stored data | MUST | R-03, R-04, R-07, R-08 | I, T |
| R-37 | **Shared, inspectable workflow state** passed between nodes | MUST | R-02 | T AT-03 |
| R-38 | **Checker isolation**: the fact-checker receives only claim, labels and code-located source passage; it SHOULD use a different model family from the extractor `[open Q-07]` | MUST (isolation) / SHOULD (model family) | R-04 | T AT-07 |
| R-47 | **Claim status lifecycle** (extracted → supported / refuted / insufficient → contested / superseded), visible and queryable | MUST | R-04, DQ-11 | T AT-08 |
| R-61 | **Bounded loops and guaranteed termination**: every loop has a budget; a run always ends with partial results and coverage status | MUST | R-09, R-50 | T AT-19 |
| R-62 | **Version stamping**: each run and each verdict records model IDs and prompt versions | SHOULD | R-04, reproducibility | I |
| R-69 | **Model per agent role is configuration**, changeable without code edits, and recorded on outputs | SHOULD | owner decision: best-fit model per agent | I |
| R-75 | Runs are resumable after a crash without re-fetching | COULD | R-09 | T |

### 7.4 Collection

| ID | Requirement | Priority | Traces to | Verify |
|---|---|---|---|---|
| R-39 | Extract figures from **PDF tables** as well as HTML | SHOULD | T-14, many primary statistics are in PDFs | T |
| R-40 | Crawl decisions are **logged with reasons**, and blocks **reroute** or become recorded gaps; applies to third-party fetchers | MUST | R-03 | T AT-04, AT-06 |
| R-41 | **Source tiering** (official or multilateral, academic, NGO, news, other) recorded on every source and used in confidence and conflict ordering | MUST | DQ-03, T-08 | T |
| R-42 | **Language handling**: queries and extraction work in the city's language; quotes kept in the original with a translation | SHOULD | R-01, A-02 | T |
| R-58 | **Search is for URL discovery only**: search snippets are never used as evidence; only permission-gated fetched content can support a fact. Search adapters run in **links-only mode**: provider features that fetch or return page content (raw content, extract endpoints) are disabled `[v1.1]` | MUST | R-03, R-07 | T AT-06, AT-33 |
| R-59 | **Prefer official APIs** where a site disallows crawling but offers an API | SHOULD | R-03 | I |
| R-68 | **Reachability states are distinct**: blocked by policy, unreachable (network, geo-block, 5xx), and not found are recorded and shown differently | SHOULD | R-16, T-15 | T |

### 7.5 Trust and evaluation

| ID | Requirement | Priority | Traces to | Verify |
|---|---|---|---|---|
| R-46 | An **evaluation harness** of planted cases (national figure as city, missing denominator, fabricated quote, unsupported claim, stale figure, injection page) that visibly trips the checks | MUST | R-26, R-04, R-08 | T |
| R-48 | **Legible confidence** computed from stated inputs (source tier, recency, geography match, verdict); it changes what is shown | SHOULD | C5, R-30 | T |
| R-56 | **Verbatim quote grounding**: a claim is kept only if code locates its quote exactly in the fetched text, after the same normalisation of both (Unicode form, whitespace, line-break hyphenation); no fuzzy matching; the drop rate is recorded per run | MUST | R-07, T-11 | T AT-09 |
| R-63 | **Answers use only verified, stored evidence**; question answering never researches inline and never uses unverified text as fact | MUST | R-04, R-08 | T AT-28 |
| R-64 | **Deterministic answer post-check**: every sentence cited; every number appears in its cited evidence; scope words (city, national, district) match the evidence's geography; proper names in a sentence must appear in the question or the cited evidence; outdated figures carry their year; every requested slot is covered by a fact or an abstention (LLD-5 §9) | SHOULD | R-07, R-08 | T AT-28 |
| R-65 | **Conflicts are surfaced**, with both values and sources, never silently resolved | MUST | DQ-06, T-02 | T AT-20 |
| R-66 | A reviewer can see and resolve contested and low-confidence items after storage (no pre-storage gate) | COULD | DQ-04, U-03 | D |

### 7.6 Operations, security and engineering

| ID | Requirement | Priority | Traces to | Verify |
|---|---|---|---|---|
| R-49 | **Asynchronous runs with streamed progress**; the interface never appears frozen during a multi-minute run; replay and disconnect handling in R-80 | MUST | R-09, DS-1 | T AT-17, AT-30; D |
| R-50 | **Cost and abuse controls**: per-run budget caps (tokens, fetches, wall clock), rate limiting, access code | MUST | R-09 | T AT-19 |
| R-51 | **Secrets management and demo fallback**: no secrets in the repo; a previously researched city and a pre-generated report available if live research stalls | MUST | R-09, R-28 | I; D |
| R-54 | **Decision and cut log** maintained throughout (`docs/DECISIONS.md`): decision, options, choice, reason, date | MUST | brief's closing note, R-28 | I |
| R-67 | **Fetch safety**: block requests to private, loopback and metadata addresses (SSRF); limit response size and content types | MUST | R-09 (public URL) | T AT-23 |
| R-71 | **Tracing**: every run is traceable step by step (node, inputs, outputs, cost, latency) for the demo and debugging | MUST | R-02, DS-2 | I; D |
| R-72 | **Question-answering latency** within interactive tolerance `[target in Q-03]` | SHOULD | R-27, DS-5 | T |
| R-73 | **Automated tests for every MUST trust rule** (crawl gate, quote grounding, geography flag, checker consequence, post-check) | MUST | R-28 | T |
| R-74 | **Fetched content is untrusted input**: instructions inside web pages never change agent behaviour | MUST | R-09, R-08 | T AT-22 |

### 7.7 Added in v1.1 (from the brainstorm)

Reasoning for each item is in `docs/design/BRAINSTORM.md`.

| ID | Requirement | Priority | Traces to | Verify |
|---|---|---|---|---|
| R-77 | **Health check and keep-alive**: a `/health` endpoint checks every store and external provider; hosting tiers that sleep or suspend are avoided, or kept alive on a schedule, for the whole evaluation window; the health check runs before every rehearsal and the demo | MUST | R-09; BRAINSTORM F10 | T AT-29 |
| R-78 | **One main badge per fact**, chosen by severity: Not city-level > Sources disagree > Outdated > Limited sample. Other flags appear in the evidence panel | MUST | R-08, R-16, R-30 | T AT-31 |
| R-79 | **Slots are the unit of work**: research uses the slot catalogue (§3.1); every slot ends a run in exactly one status with the queries tried and sources checked; slots drive planning, parallelism, sufficiency, the coverage grid, report sections and gap records | MUST | DQ-01, DQ-05, DQ-12, R-16 | T AT-32 |
| R-80 | **Replayable progress**: runs execute as background tasks independent of the browser connection; every progress event is stored; a reconnecting client resumes from the last event it received; closing the browser does not stop the run | MUST | R-09, R-49, DS-1 | T AT-30 |
| R-81 | **Vendor neutrality (ports and adapters)**: every external dependency (model per agent role, embeddings, search, each store, snapshots, tracing, hosting) sits behind an interface; the provider is chosen in configuration; vendor SDKs are imported only in the adapters layer; each port has contract tests every adapter must pass | MUST | owner requirement | T AT-34, AT-35 |
| R-82 | **Configuration validated at start-up**: refuse to start if the checker's model family equals the extractor's (unless an explicit fallback flag is set and shown in the trace), or if a store would mix embedding models | SHOULD | R-04, R-38, R-81 | T AT-36 |
| R-83 | **Research always runs fresh**; previously researched cities are reachable only through "Open existing", with the run date shown | MUST | R-01 | T AT-37 |
| R-84 | **Run summary**: claims extracted, confirmed, rejected, insufficient and dropped (quote not found); sources blocked and unreachable; time and model cost of the run | SHOULD | R-26 | T AT-38 |
| R-85 | **Structured sources first (Wave 0)**: a generic, country-keyed registry of public data APIs is queried before web search, giving cited, flagged national or sub-national figures within seconds | SHOULD | R-01, R-16, DS-1 | T |
| R-86 | **Crawl standards**: RFC 9309 including error handling; `Content-Usage` opt-outs honoured; honest user-agent | SHOULD | R-03 | T AT-04, AT-33 |
| R-87 | **Statistic values are owned by the relational store**; the graph links indicators, places and sources, and numeric values are never superseded by the graph's automatic contradiction handling | MUST | T-02, R-35, R-65 | T AT-20 |
| R-88 | **Graph switch for demonstration**: an admin control disables graph retrieval for one question to show the difference | SHOULD | R-05, DS-5 | D |
| R-89 | **Required and optional labels**: required labels must be present for a figure to be shown; labels the source does not state stay empty and flagged, never inferred | MUST | R-08, R-33 | T AT-14 |
| R-90 | **Plain user-facing vocabulary**: Confirmed · Reported, not confirmed · Not city-level · Not found · Sources disagree. Internal terms (claim, verdict, entailment) never appear on screen | SHOULD | R-27, R-30 | D |
| R-91 | **Demo-day change freeze**: no deploys on rehearsal or demo days; health check an hour before | SHOULD | R-09, R-80 | I |

### 7.8 Added by CHG-01 (retrieval for reliable answers)

Design: `docs/design/LLD-5-retrieval.md`.

| ID | Requirement | Priority | Traces to | Verify |
|---|---|---|---|---|
| R-92 | **Confirmed claims are searchable by meaning**: every supported or contested claim is indexed in a claim collection in Qdrant and searched for every question | MUST | R-06, R-15 | T AT-43 |
| R-93 | **Keyword route**: claims are searchable by exact terms (acronyms, survey names, numbers) through Postgres full-text search, and entity names through their aliases | MUST | R-15, R-43 | T AT-42 |
| R-94 | **Slot anchors**: for every slot a question asks about, the slot's best confirmed claim (or its gap record) is in the evidence bundle, whether or not any search route found it | MUST | R-15, R-16 | T AT-40 |
| R-95 | **Re-validation**: every candidate from Qdrant or Graphiti is re-checked against Postgres (city, latest run, status, time) before entering the bundle; scope violations in the bundle are zero | MUST | R-07, R-08, R-63 | T AT-39 |
| R-96 | **Contested pairs together**: an answer that cites one side of a disagreement shows both, repaired by code from stored values when needed | MUST | R-65, R-08 | T AT-41 |
| R-97 | **Retrieval trace** stored with every answer: routes, removals, anchors, bundle, post-check actions | SHOULD | R-07, DS-5 | T AT-46 |
| R-98 | **Follow-up questions** use the previous turn's classification (not its answer text) | SHOULD | R-15, R-27 | T AT-44 |
| R-99 | **Retrieval evaluation gates** met before the demo: zero scope violations; 100% abstention correctness and contested completeness on fixtures; bundle recall ≥ 0.95 on fixtures and ≥ 0.90 with real models | MUST | R-26 | T AT-47 |
| R-100 | **Multilingual embeddings** in every configuration profile | SHOULD | R-42 | I |

---

## 8. Data-quality hazards the system must handle (T-xx)

Found during analysis probes. Each hazard is a concrete way a cited statement can still mislead. Ranked by how often they were met.

| ID | Hazard | Why it misleads | Required behaviour | Requirements |
|---|---|---|---|---|
| T-01 | Wider-area figure presented as the city's (national, state, district, metro) | City may differ sharply from the wider mean | Tag geography level; flag any mismatch visibly | R-08, R-33 |
| T-02 | Same metric, conflicting values across sources | Usually caused by threshold, age band or method, not real disagreement | Store definition, threshold, age, method; compare only compatible figures; show conflicts | R-35, R-65 |
| T-03 | Sub-population figure presented as general (students, staff, older adults, clinic patients) | Selection can change a rate many-fold | Tag population scope; never generalise | R-33 |
| T-07 | Old figure presented as current (a survey still cited as "latest" years later) | Reads a dated number as today's | Show reference period; flag staleness | R-08, R-30 |
| T-05 | Programme in one region presented as active in the city | Implies presence where there is none | Record where a programme operates; national ≠ present here | R-08, CR-02 |
| T-06 | Planned or announced presented as running | Intent shown as reality | Record status and date | CR-02 |
| T-09 | Percentage with no stated denominator | Cascade percentages are meaningless without their base | Record denominator and whether stated; mark non-comparable | R-33, R-34 |
| T-04 | Screening or campaign figures presented as prevalence | Self-selected samples and activity counts are not population rates | Distinguish measure types (screening positivity, programme output) | R-33 |
| T-08 | News restatement differs from the primary source | Rounding, redefinition, misattribution | Prefer primary; lower tier for news | R-41 |
| T-10 | Implausible baseline fact (for example a population far off the real figure) | Corrupts per-capita and context statements | Check baselines against the gazetteer; flag outliers | R-57 |
| T-11 | "X reported..." with no locatable primary | Unverifiable second-hand claim | Require a resolvable source and a verbatim quote | R-56 |
| T-12 | Author affiliation mistaken for study setting | A study by an author based in the city is not a study of the city | Setting must be stated in the source passage | R-33, R-04 |
| T-13 | Institutional churn (body renamed, dissolved or replaced; conflicting dates) | Naming a defunct body as current | Time-bounded entities; show conflicting dates | R-60 |
| T-14 | Malformed or unlabelled tables (repeated rows without sex or age labels) | Values attributed to the wrong group | Keep tables whole with headers; drop values whose labels cannot be established | R-39, R-56 |
| T-15 | Authoritative source unreachable (geo-block, 5xx) or disallowed for crawling but available by API | Produces a false "not found" | Distinguish unreachable from not found; use APIs where offered | R-59, R-68 |
| T-16 | Homonymous places (same name, different country or region) | Research the wrong city | Resolve identity first; show it | R-57 |

**Most important to engineer against:** T-01, T-02, T-03, T-07. They are the most frequent and each is a demo-visible failure of R-08.

---

## 9. Open design questions (DQ-01 to DQ-12) `[STATED]`

The brief: *"These questions are intentionally unanswered. We want to understand how you think."*

**Requirement (MUST, part of R-20 and R-54):** each question has a documented decision in the HLD with the alternative considered and the reason. Answers live in design documents, not here.

| ID | Question | Answered in |
|---|---|---|
| DQ-01 | What does "understanding a city" consist of, and in what depth? | HLD (content model; must map to CR-01–CR-08) |
| DQ-02 | How should research be planned? | HLD |
| DQ-03 | How should sources be evaluated? | HLD |
| DQ-04 | Should humans review information before it is stored? | HLD |
| DQ-05 | How do you know when research is sufficient, and what happens when it isn't? | HLD |
| DQ-06 | How should conflicting information be handled? | HLD |
| DQ-07 | How should institutional memory be represented over time? | HLD |
| DQ-08 | How should relationships between people, organisations, programmes and policies be modelled? | HLD / LLD |
| DQ-09 | What information belongs in which type of datastore? | HLD / LLD |
| DQ-10 | How should conversational retrieval work? | HLD |
| DQ-11 | How should the system distinguish between facts and assumptions? | HLD |
| DQ-12 | How should missing information be represented? | HLD |

---

## 10. Deliverables (R-18 to R-23) `[STATED]`, all MUST

| ID | Deliverable | "Good" means | Location in repo |
|---|---|---|---|
| R-18 | Working application | Panel opens the URL and researches, explores, asks and traces without help | deployed; URL in `README.md` |
| R-19 | Source code | Clean, runnable; setup instructions; environment configuration guidance (`.env.example`) | repo root, `README.md` |
| R-20 | Architecture overview | Concise: components, AI and agent architecture, data architecture, retrieval strategy, key trade-offs and decisions (including DQ answers) | `docs/ARCHITECTURE.md` |
| R-21 | Example output | One complete city report generated by the system, with citations, flags and gaps | `samples/` |
| R-22 | Presentation deck, 5–8 slides | Problem as understood; AI solution and architecture; trust and evidence; user experience; trade-offs and limitations | `deck/` |
| R-23 | Repository submission | Everything needed to understand, reproduce and demonstrate: code, agent workflows, deployment config, architecture docs, deck, setup, samples | GitHub or GitLab |

---

## 11. Evaluation criteria (R-24 to R-28) `[STATED]`

| ID | Criterion | Weight | What the panel must be able to see | Main requirements |
|---|---|---|---|---|
| R-24 | Architecture and system thinking | 30% | A coherent decomposition of an ambiguous problem; a walkable workflow; clear responsibilities | R-02, R-36, R-37, R-54, DQ answers |
| R-25 | AI and data design | 25% | Agents, orchestration and stores combined appropriately and responsibly; every store justified | R-03–R-06, R-38, R-43–R-45 |
| R-26 | Trustworthiness and evidence | 20% | Where each fact came from, and what is not known | R-04, R-07, R-08, R-16, R-46, R-56, R-63–R-65 |
| R-27 | Product and user experience | 15% | A non-technical user succeeds without help | R-14, R-15, R-17, R-29–R-31, R-52 |
| R-28 | Engineering quality and communication | 10% | Code quality, deployment, maintainability, docs, clarity of deck and demo | R-09, R-19, R-22, R-51, R-73 |

**How to read the weights** `[INFERRED]`
- **55% (R-24 + R-25) is systems design.** The most rewarded skill is decomposing an ambiguous problem coherently.
- **20% trust** is high for "don't lie and prove it" and is where the non-negotiables cluster. Cheap to score if built in from the start, expensive to retrofit.
- **10% engineering is a floor, not a footnote.** A failed demo discounts everything else.
- **The closing note decides the grade:** *"We are far more interested in how you frame the problem, how you make decisions, what trade-offs you choose, and what you deliberately choose not to build."* Reasoning, honest limits and the cut list are scored work.

---

## 12. Demonstration acceptance scenarios (DS-1 to DS-7) `[STATED]`

The panel *may* ask for each step. Each must pass live.

| ID | Step | Pass criteria | Likely failure | Required fallback |
|---|---|---|---|---|
| DS-1 | Research a city we select | Run starts on any named city; progress streams; brief and gaps appear within tolerance; sparse result is honest and well presented | Sparse, non-English or ambiguous city; sources blocked or geo-restricted; slow run | Start the run first and present while it runs; show a previously researched city; designed gaps view (R-52); health check an hour before (R-77) |
| DS-2 | Explain the architecture and workflow | Graph rendered from code; nodes, edges and loops narrated; live trace matches | Diagram does not match code | Rendered graph plus trace (R-71) |
| DS-3 | Show how information is collected and verified | A real blocked source and its reroute; a claim refuted or marked insufficient with a visible consequence | Checker always passes | Planted case from the evaluation harness (R-46) |
| DS-4 | Demonstrate how findings can be explored | Executive summary, then content areas, entities and relationships, filters | Technical or empty interface | Previously researched city |
| DS-5 | Ask questions against the generated knowledge | Cited answers, including one exact-figure question and one graph-only question; abstains where unknown | Uncited or invented answer | Prepared question list known to exercise each store |
| DS-6 | Trace answers back to supporting evidence | Any fact opens source, verbatim passage, dates, geography, verdict and the preserved snapshot | Dead link; figure not in source; unflagged national figure | Snapshot store (R-55) |
| DS-7 | Discuss trade-offs and limitations | Cut list with reasons; named limits (freshness, sparse cities, cost, unreachable sources) | Overclaiming | `docs/DECISIONS.md`, deck slide |

---

## 13. Acceptance test catalogue (AT-xx)

Written as Given / When / Then so they translate directly into tests. *Demo-only* tests are checked by rehearsal.

| ID | Test | Requirements |
|---|---|---|
| AT-01 | **Given** empty stores, **when** a run is requested for a city, **then** outbound fetches are logged after the request time and city records exist only after the run | R-01, R-10 |
| AT-02 | **Given** the repository, **when** runtime prompts, config, fixtures and seed scripts are scanned, **then** they contain no city-specific facts or per-city URL lists (test fixtures use a synthetic or non-demo city) | R-01 |
| AT-03 | **Given** the compiled workflow, **when** it is rendered, **then** conditional edges exist for crawl decision, verdict routing and sufficiency loop, and state is inspectable between nodes | R-02, R-37 |
| AT-04 | **Given** a URL disallowed by robots.txt, **when** the workflow reaches it, **then** zero content requests are made to it, the decision and reason are logged, and the slot is rerouted or recorded as a gap | R-03, R-40 |
| AT-05 | **Given** a site with crawl-delay N, **when** multiple pages are fetched, **then** requests are spaced at least N seconds apart | R-03 |
| AT-06 | **Given** any content extraction (direct or via a third-party tool), **then** it passes the crawl gate first, and search snippets are never stored as evidence | R-03, R-58 |
| AT-07 | **Given** a claim to verify, **when** the checker is invoked, **then** its input contains only claim, labels and code-located passage, with no producer prompt or reasoning | R-04, R-38 |
| AT-08 | **Given** a planted claim not supported by its passage, **when** checked, **then** verdict is refuted or insufficient; the claim is absent from the graph and from answers as fact; it is recorded with reason; the gap is visible | R-04, R-47 |
| AT-09 | **Given** an extracted quote that does not occur verbatim in the source, **then** the claim is dropped | R-07, R-56 |
| AT-10 | **Given** a researched city, **when** a relationship or "as of date" question is asked, **then** it is answered from the graph; with the graph disabled the answer degrades or abstains; superseded facts are shown as superseded | R-05, R-44, R-53, R-60 |
| AT-11 | **Given** a set of questions of different types, **when** answered, **then** the trace shows reads from the relational, vector and graph stores | R-05, R-06 |
| AT-12 | **Given** any fact in an answer, report or explorer, **then** it resolves to URL, publisher, publication date, retrieval date, verbatim passage, geography level and verdict | R-07, R-13, R-45 |
| AT-13 | **Given** only a national figure for an indicator, **when** the user asks about the city, **then** the figure is shown with a visible national flag and a statement that no city figure was found | R-08, R-16 |
| AT-14 | **Given** a sub-population or stale figure, **then** it is shown with its population and reference period and flagged | R-08, R-33 |
| AT-15 | **Given** no evidence for a named office-holder, **when** asked who holds the role, **then** the system abstains rather than naming anyone | R-08, R-63 |
| AT-16 | **Given** a data-sparse city, **when** researched, **then** the run completes, the gaps view lists what was searched and not found, and no city-level figure is fabricated | R-16, R-52 |
| AT-17 | **Given** the deployed URL, **when** opened from an external network, **then** a run can be started and progress streams to the browser | R-09, R-49 |
| AT-18 | **Given** a completed run, **when** the report is downloaded, **then** it contains citations for every fact, flags and a gaps section | R-17, R-32 |
| AT-19 | **Given** a deliberately tiny budget, **when** a run executes, **then** it terminates with partial results and coverage status | R-50, R-61 |
| AT-20 | **Given** two incompatible figures for one indicator, **then** both are shown with sources and the reason they differ; neither overwrites the other | R-35, R-65 |
| AT-21 | **Given** a care-cascade percentage with no stated denominator, **then** it is flagged and not combined with figures from other sources | R-33, R-34 |
| AT-22 | **Given** a fetched page containing instructions to the model, **then** agent behaviour and outputs are unaffected | R-74 |
| AT-23 | **Given** a URL resolving to a private, loopback or metadata address, **then** the fetch is refused | R-67 |
| AT-24 | **Given** an ambiguous city name, **then** the system disambiguates or shows the identity it chose before researching | R-57 |
| AT-25 | **Given** a city researched earlier, **when** a new session opens it, **then** its knowledge is available without re-running and the run date is shown | R-12, C2 |
| AT-26 | **Given** alias forms of one organisation (full name, acronym, short form), **then** they resolve to one entity | R-43 |
| AT-27 | **Given** a source whose live page has changed since retrieval, **then** the evidence view shows the preserved snapshot | R-55 |
| AT-28 | **Given** a drafted answer containing a number not present in its cited evidence, **then** the post-check removes it or converts that part to an abstention | R-63, R-64 |
| AT-29 | **Given** the deployed system, **when** `/health` is called, **then** it reports the status of Postgres, Qdrant, Neo4j and each configured external provider, and fails if any is down or asleep | R-77 |
| AT-30 | **Given** a research run in progress, **when** the browser disconnects and reconnects, **then** the run has continued and the client receives every event after the last one it saw, with none duplicated | R-49, R-80 |
| AT-31 | **Given** a fact carrying several flags, **then** its main badge is the most severe by the fixed order and the others appear in the evidence panel | R-78 |
| AT-32 | **Given** any completed or budget-stopped run, **then** every slot in the catalogue has exactly one status, and every slot not `answered` lists queries tried and sources checked | R-79 |
| AT-33 | **Given** the configured search adapter, **when** a search is made, **then** the request disables content retrieval, and no page content enters the system except through the crawl gate and fetcher | R-58, R-86 |
| AT-34 | **Given** the source tree, **when** the import-lint test runs, **then** no module outside the adapters layer imports a vendor SDK | R-81 |
| AT-35 | **Given** each port, **then** every configured adapter passes the same contract tests | R-81 |
| AT-36 | **Given** a configuration where checker and extractor share a model family without the fallback flag, **then** the application refuses to start with a clear message | R-82 |
| AT-37 | **Given** a city already in storage, **when** the user chooses "Research", **then** a new live run starts and outbound fetches are logged; "Open existing" shows the stored run with its date | R-01, R-83 |
| AT-38 | **Given** a completed run, **then** its summary shows claim counts by outcome, blocked and unreachable sources, time and model cost | R-84 |
| AT-39 | A refuted claim present in Qdrant with a stale `supported` payload never reaches the bundle | R-95 |
| AT-40 | A question on a slot whose best claim no route returns still gets that claim (anchored) | R-94 |
| AT-41 | Citing one side of a contested pair yields both sides in the final answer | R-96 |
| AT-42 | An acronym question ("What does the GHS run?") finds claims about the full organisation name | R-93, R-43 |
| AT-43 | A question phrased differently from any claim's wording ("how many adults have high blood pressure") finds the prevalence claim through the semantic route | R-92 |
| AT-44 | A follow-up "and nationally?" after a city question on S03 retrieves S03 claims | R-98 |
| AT-45 | A sentence naming a person absent from the evidence is removed | R-08, AT-15 |
| AT-46 | Every answer stores a trace with routes, removals, anchors, bundle and post-check actions | R-97 |
| AT-47 | The fixture evaluation meets every gate in LLD-5 §12.3 | R-99 |

---

## 14. Constraints (CON-xx)

| ID | Constraint | Status |
|---|---|---|
| CON-01 | Timebox: brief says 2–3 days; owner has 4 working days including design | `[STATED]` brief / owner decision |
| CON-02 | Orchestration: LangGraph | `[decided]` (brief allows comparable) |
| CON-03 | Knowledge graph: Graphiti (not substitutable), on Neo4j | `[STATED]` Graphiti / `[decided]` Neo4j |
| CON-04 | Relational: PostgreSQL. Vector: Qdrant (separate engine). Graph: Graphiti on Neo4j Community. All run from container images, locally and deployed | `[decided]` |
| CON-05 | Models chosen per agent role in configuration. Deployed defaults: Claude Sonnet 5.5 (planner, router, answerer, report writer); Claude Haiku 4.5 (extraction, escalating hard documents to Sonnet 5.5); an OpenAI frontier model as checker (ID confirmed day 1); Claude Opus 5.5 as labelled same-family checker fallback. Embeddings: OpenAI small model deployed, local Sentence Transformers for development | `[decided]` default adapters |
| CON-06 | Frontend React / Next.js, built as a static site; backend FastAPI | `[decided]` |
| CON-07 | Hosting default: Render, paid instances billed by the second; stores as private services with disks. Any container host works through Docker Compose | `[decided]` default adapter |
| CON-08 | Public sources only; respect robots.txt and terms of use; no circumvention of paywalls, logins or blocks | `[STATED]` via R-03 / `[INFERRED]` |
| CON-09 | All deliverables in one GitHub or GitLab repository | `[STATED]` |
| CON-10 | Spend capped: one run at a time, at most 20 runs a day; per run about 60 fetches and 7 minutes (420 s, owner 2026-10-03, BD-15); $3 and 1.5M tokens per run (measured by spike S-6, BD-15); provider-level monthly limits as a second safety net | `[decided]` |
| CON-11 | Not tied to any paid service: every provider is an adapter chosen in configuration (R-81). Free or self-hosted adapters exist for every port; only public hosting (R-09) necessarily runs somewhere | `[decided]` owner requirement |
| CON-12 | Search default: Brave Search API in links-only mode when deployed; SearXNG for local development. Tracing: own progress events always on; LangSmith free tier switchable | `[decided]` default adapters |

---

## 15. Assumptions (A-xx)

| ID | Assumption | How to check |
|---|---|---|
| A-01 | The City Lead is non-technical | Brief wording; confirm with panel |
| A-02 | The panel may pick any city, including sparse, non-English or ambiguous ones | Design for it; confirm (Q-01) |
| A-03 | LangGraph is acceptable | Named in the brief |
| A-04 | Reopening a previously researched city from storage is acceptable if the run date is shown and unseen cities always research live | Confirm (Q-02); keep the live path independent of any cache |
| A-05 | The panel will probe trust adversarially | Implied by R-07, R-08; design defensively |
| A-06 | A run of a few minutes with streamed progress is acceptable | Confirm (Q-03); measure on day 1 |
| A-07 | Graphiti supports the needed relationship and temporal queries within the latency budget | Day-1 spike |
| A-08 | A search API returns usable results for arbitrary cities worldwide | Day-1 test on one sparse and one random city |
| A-09 | Generic reference data (gazetteer, source-type registry, indicator definitions) is not "pre-seeded city data" | Argue in architecture doc; confirm if possible |
| A-10 | Some authoritative sources are unreachable from the hosting region (HTTP 503 seen from outside India in probes; geo-restriction not confirmed) | Day-1 reachability test from the deployed region |
| A-11 | An English interface is acceptable; non-English sources are quoted in the original with translation | Confirm |
| A-12 | Protecting the URL with an access code given to the panel is acceptable | Confirm (Q-05) |
| A-13 | The deployed region can reach the WHO, DHS and World Bank APIs, and WHO's current endpoint is known | Day-1 call from the deployed host |
| A-14 | Prepaid model credits of about $25 (Anthropic) and $15 (OpenAI) cover development before top-up | Day-1 per-run cost measurement |

---

## 16. Open questions (Q-xx): resolved in v1.1

Every question now has a decided default (reasoning in `docs/design/BRAINSTORM.md` §11). Items still needing outside confirmation are marked.

| ID | Question | Resolution | Still to confirm |
|---|---|---|---|
| Q-01 | Will the panel choose the city; could it be sparse, non-English or ambiguous? | Assume yes; rehearse sparse, non-English, ambiguous and the three pioneer cities | — |
| Q-02 | Is reopening a stored city acceptable? | Yes, through "Open existing" with the run date; "Research" always runs fresh (R-83) | — |
| Q-03 | Latency the demo tolerates | First findings within about 20 s (Wave 0); full run under 7 min (owner 2026-10-03, BD-15); answers under about 15 s | Measure day 1 |
| Q-04 | Health scope | Three risk factors plus stroke and heart-attack outcomes | — |
| Q-05 | Access code on the URL | Yes | — |
| Q-06 | Report format | Markdown or HTML, plus PDF | — |
| Q-07 | Checker model family | Different family (OpenAI) over Anthropic extraction; labelled same-family fallback (R-82) | Model ID day 1 |
| Q-08 | Entity resolution without a trained model | Yes: normalise names, acronym map from the sources, embedding merge | — |
| Q-09 | Exact model IDs | Sonnet 5.5, Haiku 4.5, Opus 5.5 fallback | OpenAI IDs day 1 |
| Q-10 | Geo-restricted sources | Record `unreachable` honestly; prefer global sources; no proxy unless the example city needs one | Reachability test day 1 |
| Q-11 | Spend caps | CON-10 | Token cap after day-1 measurement |
| Q-12 | Demo format, length, and gap after submission | Plan for 45–60 min with a 30-min short version | **Ask the recruiter** |

---

## 17. Out of scope for the PoC (WON'T)

Each item is a deliberate choice for the cut list (R-54), not an omission.

| Item | Reason | What would bring it back |
|---|---|---|
| Trained ML models (entity-resolution classifier, confidence calibrator) | No time to label training data | Labelled pairs from real runs |
| Human review before storage | Autonomy is the point; flags and post-hoc review cover the risk | Production use with high-stakes facts |
| User accounts, roles, collaboration, annotation | Single demo audience | Multi-team rollout |
| Cross-city comparison interface | The data model supports it; the screen is not needed for the demo | Second city in production |
| Scheduled refresh and change detection | Temporal model supports it; no scheduler | Ongoing programme use |
| Paywalled, login-protected or terms-prohibited sources | Not permitted (CON-08) | Licensed data access |
| Social media collection | Terms of use and reliability | n/a |
| Exhaustive PDF layouts, scanned documents (OCR) | Time sink; common table layouts only, honest failure otherwise | Measured false-gap rate |
| Age standardisation and epidemiological normalisation | Show method metadata instead | Epidemiologist on the team |
| Monitoring dashboards beyond tracing | Tracing plus logs suffice for the demo | Production |
| Headless browser for JavaScript-rendered pages | Weight, cost and failure modes; unreadable pages recorded honestly | Measured share of unreadable sources |
| Search-vendor content extraction | Would bypass the crawl gate (R-03, R-58) | Never |
| Neo4j analytics plugin | Not available on free graph tiers; centrality computed in the app | A paid graph tier with analytics |
| Separate worker service for runs | One process suffices for one run at a time | Production concurrency |

---

## 18. Traceability

### 18.1 Brief requirements to evaluation, demo and tests

| Requirement | Criterion | Demo step | Acceptance tests |
|---|---|---|---|
| R-01 Live research | R-25 | DS-1 | AT-01, AT-02, AT-37 |
| R-02 Agentic workflow | R-24 | DS-2 | AT-03 |
| R-03 Crawl gate | R-25, R-26 | DS-3 | AT-04, AT-05, AT-06, AT-33 |
| R-04 Independent checker | R-25, R-26 | DS-3 | AT-07, AT-08 |
| R-05 Graphiti at query time | R-25 | DS-5 | AT-10, AT-11 |
| R-06 Three stores | R-25 | DS-2, DS-5 | AT-11 |
| R-07 Evidence on every fact | R-26 | DS-6 | AT-09, AT-12, AT-27 |
| R-08 No fabrication / geography flag | R-26 | DS-1, DS-6 | AT-13, AT-14, AT-15, AT-21 |
| R-09 Deployed URL | R-28 | DS-1 | AT-17, AT-29, AT-30 |
| R-10 Unseen city | R-24 | DS-1 | AT-01, AT-16 |
| R-11 External collection | R-25 | DS-3 | AT-04 |
| R-12 Structured findings | R-25 | DS-4 | AT-25 |
| R-13 Evidence references | R-26 | DS-6 | AT-12 |
| R-14 Exploration | R-27 | DS-4 | demo-only |
| R-15 Question answering | R-27 | DS-5 | AT-10, AT-28, AT-39, AT-40, AT-41, AT-47 |
| R-16 Uncertainty and gaps | R-26 | DS-1, DS-6 | AT-13, AT-16, AT-31, AT-32, AT-41 |
| R-17 Downloadable report | R-27 | (after DS-4) | AT-18 |

### 18.2 Capabilities to content areas

| Capability | Content areas exercised |
|---|---|
| C1 Gather and organise | CR-01 to CR-08 |
| C2 Reusable asset | all, through the stores (R-05, R-06, R-45) |
| C3 Explore and understand | all, through R-14, R-15, R-29 |
| C4 Evidence | CR-06 (the layer under all others) |
| C5 Uncertainty and quality | CR-01 especially; T-01 to T-16 |

---

## 19. Definition of done (PoC)

The submission is complete when:
1. Every **MUST** requirement has passing acceptance tests or a rehearsed demo check.
2. DS-1 to DS-7 have been rehearsed end to end on the deployed URL, including one data-sparse city and one city chosen at random during rehearsal.
3. All deliverables R-18 to R-23 are in the repository.
4. Every DQ-xx has a documented decision in the HLD.
5. `docs/DECISIONS.md` contains the cut list with reasons, and §17 matches what was actually cut.
6. No secrets are in the repository; `.env.example` documents every variable.
7. The health check passes on the deployed URL, and no deploy is scheduled on demo day.
8. The import-lint and adapter contract tests pass.

---

## 20. Glossary

| Term | Meaning |
|---|---|
| City Lead | The CARDIO4Cities programme lead preparing to engage a city |
| Care cascade | Prevalence → screened → diagnosed → treated → controlled, per risk factor |
| Control rate | Share of people with a condition whose measures are within target (for hypertension, blood pressure controlled) |
| Claim | One statement extracted from one source, with its verbatim quote and metadata |
| Verdict | The fact-checker's judgment on a claim: supported, refuted or insufficient |
| Geography level | The area a figure actually describes (city, sub-city area, metro, district, state or province, national, global) |
| Provenance spine | The ID links by which every stored fact resolves to its claim, verdict, source and snapshot |
| Snapshot | The source exactly as fetched, with content hash and retrieval time |
| Gap | A content area searched without finding acceptable evidence, recorded with what was tried |
| Crawl gate | The step that decides whether a URL may be fetched, before any fetch |
| Build path / query path | Research that writes verified knowledge / question answering that only reads it |
| Slot | A fixed research question that a program can mark answered or not; the unit of work (§3.1) |
| Main badge | The single most severe flag shown on a fact; other flags sit in the evidence panel |
| Port / adapter | An interface for an external dependency / one provider's implementation of it, chosen in configuration |
| Wave 0 | The first research step: generic structured public-data APIs queried before web search |

---

## Change log

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-10-02 | Baseline. Brief requirements R-01–R-28 restated with strict readings and acceptance criteria; derived requirements R-29–R-54 carried over; R-55–R-76 added from prior design work and probes; hazards T-12–T-16 added; acceptance test catalogue AT-01–AT-28 created. |
| 1.1 | 2026-10-02 | Moved to `docs/design/`. Added slot catalogue and statuses (§3.1); R-77–R-91 (health check and keep-alive, one main badge, slots as unit of work, replayable progress, vendor neutrality, config validation, research always fresh, run summary, Wave 0, crawl standards, statistics owned by Postgres, graph switch, required labels, plain vocabulary, demo-day freeze); tightened R-01, R-03, R-30, R-49, R-56, R-58; AT-29–AT-38; CON-04–CON-12 updated to decided defaults; A-13, A-14; all Q-xx resolved (Q-12 added); WON'T list extended. |
| 1.2 | 2026-10-03 | CHG-01: R-92–R-100, AT-39–AT-47, R-64 extended; retrieval design in LLD-5. |
| 1.3 | 2026-10-03 | Owner, after spike S-6 (BD-15): CON-10 and Q-03 allow 7 minutes per run; CON-10 records the measured caps ($3, 1.5M tokens). |
