# CARDIO4Cities City Intelligence: Design Brainstorm

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-10-02 |
| **Status** | Complete. Decisions here are binding defaults for the HLD; changes need a `docs/DECISIONS.md` entry. |
| **Inputs** | The case-study brief · `docs/design/REQUIREMENTS.md` v1.1 · prior design export from another workspace |
| **Feeds** | `docs/design/HLD.md`, `docs/DECISIONS.md`, `docs/ARCHITECTURE.md` (concise, for the panel) |

**What this is.** The record of a multi-role, multi-pass brainstorm over five parts of the brief: the open design questions, the functional expectations, what the panel cares about, the demonstration scenario, and the deliverables. It records **what was decided and why**, the research that shaped it, the PoC scope and the cut order. It is the reasoning behind requirements R-77 to R-91.

**How to read it (for Claude Code).** Sections 11 (final decisions) and 9 (scope) are the parts that bind implementation. Everything else explains them. Where this file and `REQUIREMENTS.md` differ, `REQUIREMENTS.md` wins.

---

## 0. Method

**Roles.** Nine perspectives, each arguing from its own interest:

| Role | Cares about |
|---|---|
| R1 City Lead | A brief they can repeat to officials; knowing what not to say |
| R2 Epidemiologist | Whether figures mean what they appear to mean |
| R3 Agent architect | Responsibilities, coordination, model vs code |
| R4 Data and web engineer | Permission, fetching, parsing, which sources actually exist |
| R5 Knowledge engineer | Storage, relationships, time, reuse |
| R6 Trust and evaluation lead | Verification inside the system; testing outside it |
| R7 Security, cost and ops | Public URL, spend, latency, demo reliability |
| R8 Skeptical evaluator | Grades against the brief; attacks weak points |
| R9 Delivery lead | What fits in the timebox; what gets cut |

**Passes.** Pass 1 collects role positions. Pass 2 tests them against research and the skeptic. Pass 3 converges on a PoC decision, production path, demo proof and effort. Effort: S ≤ 2 h, M 2–5 h, L 5–10 h.

---

## 1. Research findings

Paraphrased; checked 2026-10-02. Items marked `[verify]` must be confirmed on day 1.

| # | Finding | Consequence | Source |
|---|---|---|---|
| F1 | Graphiti can add a single fact (source entity, fact, target entity) directly, bypassing its own extraction. Custom entity and edge types can be declared, including which edge types may connect which entity types. Facts are edges with valid/invalid/created/expired timestamps, searchable with temporal filters. Graphs can be partitioned with `group_id`. Its model client supports Anthropic, OpenAI, Gemini, Groq, Azure and Ollama; embedders include OpenAI, Voyage, Gemini and Sentence Transformers. | Write verified facts as triplets; one partition per city | github.com/getzep/graphiti (mcp_server README); deepwiki.com/getzep/graphiti; help.getzep.com/graphiti |
| F2 | Graphiti's episode ingestion triggers several model and embedding calls per item; an open issue reports it is impractically slow for content over about 5 KB. The bulk path skips edge invalidation and should be used only for empty graphs; a recent bug report shows it writing duplicate edges. | Do not use episodes for facts; never use the bulk path | github.com/getzep/graphiti issues 1193, 1654, 1872; help.getzep.com/graphiti/graphiti/adding-episodes |
| F3 | LangGraph nodes can emit custom progress data through a stream writer; stream modes can be combined; streaming works with the Postgres checkpointer; the Send primitive supports parallel fan-out. | Streamed progress; parallel slots | docs.langchain.com/oss/python/langgraph/streaming; reference.langchain.com/python/langgraph |
| F4 | robots.txt is IETF RFC 9309 (2022), including rules for when robots.txt itself cannot be fetched. IETF AI-preferences drafts (2026) add a `Content-Usage` rule for robots.txt and HTTP headers; these are advisory preferences. | Gate follows RFC 9309 and honours `Content-Usage` opt-outs | ietf-wg-aipref.github.io/drafts/draft-ietf-aipref-attach.html; arxiv.org/html/2609.11152v1 |
| F5 | WHO's Global Health Observatory publishes national hypertension control (adults 30–79, 140/90 or medication) and modelled prevalence for almost every country. WHO announced the current OData API would be deprecated around end of 2025 in favour of a new one `[verify which endpoint works]`. | Guaranteed, flagged national floor for any city | who.int/data/gho/indicator-metadata-registry/imr-details/5659; apps.who.int/gho/data/node.resources.api |
| F6 | The DHS Program API offers about 1,500 survey indicators for about 90 countries with sub-national breakdowns; the programme has been continued and has an MCP server. | Sub-national floor for many lower-income countries | blog.dhsprogram.com/dhs-api; dhsprogram.com |
| F7 | US Healthy People 2030 defines hypertension at 130/80 and control as below 130/80, unlike WHO's 140/90. | A concrete definition trap (T-02): never compare these | odphp.health.gov (HDS-05 methodology) |
| F8 | Studies find LLM judges favour outputs from themselves and their own model family, even on objectively checkable rubrics; judging with a different family reduces this. | Checker from a different model family | arxiv.org/pdf/2604.06996; researchgate (Self-Preference Bias in LLM-as-a-Judge) |
| F9 | AuraDB Free allows 50,000 nodes and 175,000 relationships; Neo4j's analytics library needs a Professional tier or self-hosting. | Compute centrality in the app | neo4j.com/free-graph-database; neo4j.com/docs/aura/graph-analytics |
| F10 | Free tiers sleep: Qdrant's free cluster is suspended after a week unused and deleted after four; AuraDB Free lists auto-pause; Render's free web tier sleeps when idle. | Paid or kept-alive services; health check | qdrant.tech/documentation/cloud/create-cluster; neo4j.com/pricing |
| F11 | Some search APIs fetch page content themselves (Tavily's raw content and extract endpoints); Brave returns links. Free-tier figures for Brave disagree between sources (a monthly credit vs 2,000 queries at 1 request per second) `[verify]`. | Links-only search; plan for about 1 request per second | exa.ai/alternatives/brave-search-api; firecrawl.dev/blog/best-web-search-apis |
| F12 | Render allows requests up to 100 minutes, but a deploy or restart kills in-flight work; Render recommends decoupling long work from the request. Paid compute is billed by the second. | Background runs with replayable progress; no deploys on demo day; pay only for days used | render.com/articles/real-time-ai-chat-websockets-infrastructure; render.com/pricing |

## 2. Design changes from the prior architecture

| # | Change |
|---|---|
| Δ1 | Write verified facts to Graphiti as triplets, not episodes (F1, F2) |
| Δ2 | Statistic values live in Postgres; the graph links indicators, places and sources, and never auto-invalidates numbers (F7, R-87) |
| Δ3 | Stakeholder centrality computed in the app, not with Neo4j's analytics plugin (F9) |
| Δ4 | Generic, country-keyed structured sources as Wave 0 (F5, F6, R-85) |
| Δ5 | Crawl gate also honours `Content-Usage` opt-outs (F4, R-86) |
| Δ6 | Day-1 check of the working WHO endpoint (F5) |
| Δ7 | Non-sleeping or kept-alive services; health check across all stores (F10, R-77) |
| Δ8 | Search in links-only mode (F11, R-58) |
| Δ9 | Plan for about 1 search request per second (F11) |
| Δ10 | Runs as background tasks with replayable progress; no deploys on demo day (F12, R-80, R-91) |
| Δ11 | Consistency check is code comparing metadata, not a model call |
| Δ12 | Snapshots stored inside Postgres: a fourth logical store, not a fourth engine |
| Δ13 | Concise `docs/ARCHITECTURE.md` for the panel, separate from the build documents |
| Δ14 | Ports and adapters: every provider switchable in configuration (R-81) |

---

## 3. Open design questions (DQ-01 to DQ-12)

| DQ | Decision | Main alternative rejected, and why | Demo proof | Effort |
|---|---|---|---|---|
| 01 Understanding a city | Six dimensions, about 16 fixed slots (REQUIREMENTS §3.1); control rate is the headline; depth = one verified answer or one documented not-found per slot | Open-ended exploration: cannot prove coverage, not comparable across cities | Coverage grid | M |
| 02 Planning | Three waves: Wave 0 structured APIs by country code; Wave 1 model-written queries per slot (English and local language) in parallel; Wave 2 re-plan unfilled slots only, at most twice. Planner prompt contains identity and slot definitions, never city facts | Fully autonomous planner: unbounded cost and time | Plan visible in trace | M |
| 03 Source evaluation | Two deterministic axes: source tier (government/multilateral, academic, NGO, news, other) and evidence quality per claim (representativeness, method, geography fit, recency, denominator); combined into a plain label with reasons | Model scoring of sources: not legible, not reproducible | Click a label to see reasons | S |
| 04 Human review before storage | None. Automated gates, visible status, named people need two independent current sources or are shown as "not verified, confirm locally", review list afterwards (COULD) | Pre-storage review: stalls a live demo | Status labels | S |
| 05 Sufficiency | Every slot ends in one status (answered, answered_wider_geo, answered_negative, blocked, unreachable); run ends when no slot is pending or the budget is spent; insufficiency is the gaps view | Confidence threshold: opaque, can loop | Sparse-city run | M |
| 06 Conflicts | Code compares only like with like (measure, definition, population, geography). Different metadata: "not comparable", both shown. Same metadata, different values: "sources disagree", both shown, headline by fixed rule (tier, representativeness, recency, geography fit). Relationship conflicts written as attributed facts | Let the graph's contradiction handling decide: a newer 130/80 figure would wrongly replace a 140/90 one | Planted incompatible pair | M |
| 07 Memory over time | Three dates kept apart: reference period, publication date, retrieval date. Re-runs append; superseded facts end-dated. "What changed since last run" is COULD | Overwrite on re-run: loses history | "As of" question | M |
| 08 Relationships | Six entity types (Place, Organization, Person, Programme, Policy, Indicator); typed edges (GOVERNS, REPLACED_BY, PART_OF, RUNS, FUNDS, PARTNERS_WITH, OPERATES_IN, ISSUED_BY, APPLIES_TO, LEADS, MEASURED_IN); every edge carries claim IDs; written as triplets from verified claims; three graph-only questions fixed up front | Schema-free extraction: noisy, not comparable | Graph-only question, then graph switched off | L |
| 09 What goes where | Postgres proves; Qdrant finds; Graphiti connects; snapshots preserve (inside Postgres) | Vector extension inside Postgres: blurs the three-store requirement | Trace shows each store read | M |
| 10 Conversational retrieval | Read-only path: classify question; retrieve by type (figures from Postgres, relationships and time from Graphiti, open questions from Qdrant plus graph facts); evidence bundle from verified claims only; sentence-level citations; code post-check; abstain where no evidence. No inline web research | Plain vector RAG: no graph use, unverified text leaks into answers | Three question types plus one abstention | M–L |
| 11 Facts vs assumptions | Four kinds shown differently: Confirmed fact; Reported, not confirmed; Analysis (linked to source facts); Gap. Only the extractor-and-checker path creates facts | A single confidence score: hides the difference in kind | Evidence panel | S |
| 12 Missing information | Gaps are stored records with status, reason flags, queries tried and sources checked; shown in the coverage grid, the report's "What we could not find" and chat abstentions | Omission: indistinguishable from not searched | Gaps view | S–M |

---

## 4. Functional expectations (R-10 to R-17)

**Time budget for one live run** (estimate, measured on day 1):

| Stage | Estimate |
|---|---|
| Wave 0: identity and structured APIs | 10–20 s (first cited findings appear here) |
| Wave 1: about 40 search queries at about 1 per second | about 40 s |
| Fetch 40–60 pages, polite per domain | 60–90 s |
| Extraction, parallel | 30–60 s |
| Verification, per claim | 30–90 s |
| Graph writes as triplets | under 15 s |
| **Total** | **about 3–5 min, streamed** |

| FE | Minimum that counts | Key decision | Cut line | Effort |
|---|---|---|---|---|
| 1 Unseen city | Any name; identity confirmed (choice offered when ambiguous); streamed; always ends; no invented figures | Rehearse 10 random cities incl. 3 non-English, 2 ambiguous, the 3 pioneer cities | Long-tail tuning | L |
| 2 Collect | Crawl gate; HTML; PDF tables limited to pages mentioning target terms; structured APIs | Unreadable pages recorded as `unreadable` | Headless browser, OCR | M–L |
| 3 Structure | Required labels validated; unknown labels left empty and flagged, never inferred (R-89) | Required vs optional split | Optional labels on weak sources | M |
| 4 References | Normalise both texts, then exact match; snapshots; drop rate tracked (R-56) | High drop rate means fix parsing, never loosen matching | Fuzzy matching (never) | S–M |
| 5 Explore | Four screens: Start, City brief, Explore, Ask; evidence panel everywhere; network view of one entity and its neighbours | No whole-graph drawing | Network view | M–L |
| 6 Answer | Figure, relationship and open questions; abstention | Prepared question list for the demo | Research a gap from chat | M–L |
| 7 Uncertainty | One main badge per fact by severity (R-78); coverage grid; gaps view; abstentions | Avoid warning fatigue | Badge customisation | M |
| 8 Report | Assembled by code from stored verified facts; model writes only linking prose referencing claim IDs; sections: summary, six dimensions, Analysis, What we could not find, Handle with care, numbered sources | Markdown or HTML plus server-side PDF `[verify PDF library on host; fallback print stylesheet]` | Styling polish | M |

---

## 5. What We Care About

| Area | What the panel probes | Our position | How we show it | What loses points |
|---|---|---|---|---|
| WC-1 Problem decomposition (30%) | Breaking an ambiguous problem into manageable tasks | **The slot is the unit of work everywhere**: planning, parallelism, sufficiency, coverage grid, report sections, gaps | One slide at three levels: content (dimensions to slots), process (gate, fetch, extract, verify, write), responsibility (model vs code) | Decomposing by tool; overlapping agents |
| WC-2 AI and agentic design (25%) | Responsibility and coordination for trustworthy results | Five model agents (planner, extractor, checker, answerer, report writer) and two code agents (crawl gate, coverage assessor); coordination only through typed state. Agency = five decisions with consequences: re-plan, route, block, reject, loop or stop | Those five decisions in a live trace | Producer checking its own work |
| WC-3 Knowledge management (25%) | Storage, organisation, relationships, reuse | One owner per datum; provenance spine; three dates; entity resolution in three steps (normalise, acronym map from sources, embedding merge) | Reopen yesterday's city; "as of" question | Write-only graph; duplicate entities |
| WC-4 Trustworthiness (20%) | Accurate, current, supported | Accurate = checker plus exact quotes; current = three dates plus "Outdated" badge; supported = evidence panel plus snapshot. Show failures being caught | Run summary counts (R-84); trust tests in the repo; one planted case live | Confidence with no reasons; a checker that never says no |
| WC-5 User experience (15%) | Useful for a non-technical user | Progressive disclosure; one main badge; plain vocabulary (R-90) | Walk through as a City Lead | Chat-only UI; graph hairball; jargon |
| WC-6 Engineering judgment (10%, scored everywhere) | Priorities under time pressure | Deploy skeleton on day 1; spikes first; thin slice before breadth; tests on trust rules; cut list naming what would bring each cut back | `DECISIONS.md`; deck slide 7 | Polished UI on a pipeline that fails live |

---

## 6. Cross-examination: conflicts and resolutions

| Conflict | Resolution | Reason |
|---|---|---|
| Precision vs coverage | Never withhold; show with a visible badge and plain caution | Omission and silent inclusion both fail R-16 |
| Verification depth vs time and cost | Verify every claim that could be shown as a fact; keep at most about 5 claims per slot before verification, ranked by tier and geography fit; the rest stay in Qdrant as "found, not verified" | Headline facts must be bulletproof; exhaustive checking blows the budget |
| Simplicity vs evidence detail | Brief first; every fact one click from full provenance | Serves the City Lead and the "click any fact" test |
| Rules vs model judgment | Code decides; models assist; every model output validated | Auditability and reproducibility |
| Graph vs vector retrieval | Route by question type; keep graph-only questions | Proves R-05 without forcing everything through the graph |
| Autonomy vs human review | No pre-storage gate; stricter evidence rule for named people | A live demo cannot wait for a reviewer |
| Depth per layer vs end-to-end | Thin slice first; deepen only what the demo shows | The brief prefers working end-to-end over half-built |
| One badge vs completeness | Severity rule picks the badge; the rest one click away | The most dangerous error always wins |
| No headless browser vs coverage | Accept; record `unreadable`; report the measured rate | Reliability over breadth |
| Free tiers vs reliability | Paid by the second, or kept alive; health check | A dead URL fails R-09 |
| Wave 0 looks national-only | Say so: certain national floor in seconds, city research follows | Honesty is the point |

---

## 7. Demonstration scenario

**What each step really tests**

| Step | Tests | Prepared counter to live failure |
|---|---|---|
| DS-1 Research a city we select | Cold start; honesty when data is thin | Identity choice; Wave 0 findings in seconds; designed gaps view; start the run first; `unreachable` shown separately; health check an hour before |
| DS-2 Architecture and workflow | Is the graph real and coherent | Diagram generated from the compiled workflow; trace of the panel's own run |
| DS-3 Collection and verification | Gate blocks; checker says no with consequences | Run summary counts; planted case on request |
| DS-4 Exploration | Non-technical usability | Open on the City brief; plain vocabulary |
| DS-5 Questions | Grounded answers; graph genuinely used; abstention | Prepared graph-only question; admin graph switch (R-88) |
| DS-6 Trace to evidence | Real, exact, preserved sources | Snapshot beside the link |
| DS-7 Trade-offs | Judgment and honesty | Cut list; limits slide |

**Run sheet** (format unknown; plan for 45–60 minutes, with a 30-minute version):

| Time | Action | Covers |
|---|---|---|
| 0:00 | Ask for the panel's city; start the run; show identity and first national findings | DS-1 begins |
| 0:02 | Deck while the run continues | R-22 |
| ~0:12 | Back to the run: progress, coverage grid, gaps | DS-1 |
| ~0:15 | Workflow diagram plus trace of this run | DS-2 |
| ~0:20 | Crawl decisions and rejected claims; planted case if asked | DS-3 |
| ~0:25 | City brief, explore, one-entity network view | DS-4 |
| ~0:30 | A figure question, a graph-only question, one with no answer | DS-5 |
| ~0:35 | Click any fact to its source, passage, dates, geography, snapshot | DS-6 |
| ~0:40 | Trade-offs, cuts, limits | DS-7 |
| Fallback | A city researched the previous day; the stored report | R-51 |

**Rehearsal rules.** At least two full rehearsals on the deployed URL: one sparse city, one chosen at random by someone else. Rehearse the three pioneer cities (São Paulo, Dakar, Ulaanbaatar): the panel may pick one to see whether the system finds CARDIO4Cities' own work there from live sources. Before the demo, clear rehearsal cities from storage except one named fallback city.

---

## 8. Deliverables

**Two audiences, two kinds of document.** `docs/ARCHITECTURE.md` is concise (about 5–6 pages) for the panel and covers exactly the brief's list plus DQ answers. `docs/design/` holds the long build documents for Claude Code.

| ID | Deliverable | PoC scope | When |
|---|---|---|---|
| R-18 | Working application | Deployed URL, access code, health check, replayable runs | Skeleton day 1; complete day 3 |
| R-19 | Source code | README with URL and quick start; `.env.example`; Docker Compose running all stores locally | Throughout |
| R-20 | Architecture overview | `docs/ARCHITECTURE.md`, concise | Draft day 2; final day 4 |
| R-21 | Example output | One report from the deployed system, unedited, with run ID and date, for a city never used in prompts or tests; second sparse-city report COULD | Day 3–4 |
| R-22 | Deck | 7 slides (below); slide 1 exists | Built as we go; final day 4 |
| R-23 | Repository | Code, workflows, deploy config, docs, deck, samples, trust-test results | Day 4 |

**Deck outline.** 1 The problem as we understand it (done) · 2 What "understanding a city" means: dimensions, slots, sparse is normal · 3 Architecture and agent workflow: slot as unit of work, models vs code · 4 Knowledge: proves, finds, connects, preserves · 5 Trust and evidence: accurate, current, supported, failures caught · 6 The City Lead's experience · 7 Trade-offs, cuts, limits and a short production roadmap.

---

## 9. PoC scope

### 9.1 Time budget

| # | Workstream | Hours |
|---|---|---|
| W0 | Repo, local stores, deploy skeleton with all stores connected, health check | 3 |
| W1 | Day-1 spikes: Graphiti triplets, WHO endpoint, reachability from host, search API terms | 3 |
| W2 | City identity, source registry, Wave 0 | 3 |
| W3 | Search, crawl gate, fetch, snapshots, HTML and PDF parsing | 5 |
| W4 | Extraction, exact quote matching, label validation | 3 |
| W5 | Checker and consequences, consistency in code, coverage loop, budget | 4 |
| W6 | Writes to Postgres, Qdrant, Graphiti; entity resolution | 4 |
| W7 | Question answering: classify, retrieve, answer, post-check | 4 |
| W8 | Front end: four screens, evidence panel, streaming | 6 |
| W9 | Report generation | 2 |
| W10 | Trust tests | 2 |
| W11 | Deck, ARCHITECTURE.md, README, example output, rehearsals | 5 |
| | **Total** | **44** |

44 hours exceeds four days once design time is included, even with Claude Code writing most code. Claude Code accelerates W2–W9; it does not accelerate spikes, deployment problems or rehearsal. The plan therefore needs a core of about 32 hours and a clear cut order. W8 (front end) is the most likely to overrun.

| Day | Focus | Exit check |
|---|---|---|
| 1 | Finish design docs; W0; W1 | URL live; all stores reachable; spike results recorded |
| 2 | W2–W6: one slice end to end, then breadth | One city produces verified, cited facts in all stores |
| 3 | W7–W9; deploy | A user can run, explore, ask and download on the URL |
| 4 | W10; harden; W11; two rehearsals | Definition of done met |

### 9.2 Scope by priority

| Priority | Items |
|---|---|
| **MUST** | Live research for any city with identity confirmation; Wave 0; crawl gate before every fetch; HTML and PDF parsing; exact quote matching; independent checker with consequences; slot statuses and budget; Postgres, Qdrant, Graphiti (triplets) on real read paths; one graph-only question; question answering with code check and abstention; evidence panel with snapshot; one main badge; coverage grid and gaps view; report download; replayable streamed progress; deployed URL with access code and health check; trust tests; ports and adapters with import-lint; decision and cut log |
| **SHOULD** | Checker from a different model family; local-language queries and translations; "Handle with care" list; entity-resolution embedding merge; one-entity network view; run summary; graph switch; config validation |
| **COULD** | Review list for contested items; "what changed since last run"; model adjudication of borderline entities; research a gap from chat; stakeholder centrality ranking; resume after crash; second (sparse) example report |
| **WON'T** | Headless browser; OCR; review before storage; accounts and collaboration; cross-city comparison screen; scheduled refresh; paywalled or login sources; social media; search-vendor content extraction; Neo4j analytics plugin; separate worker service |

### 9.3 Cut order (top first)
1. All COULD items
2. One-entity network view (keep entity pages as lists)
3. Local-language queries (record as a limit)
4. Different-family checker (keep the isolated checker; record as a limit)
5. Entity-resolution embedding merge (keep normalisation and acronym map)
6. Report styling (keep Markdown and a plain PDF)
7. Number of slots, down to about 10, keeping the control-rate slot

### 9.4 Never cut
The nine non-negotiables; exact quote matching; the checker's consequences; the honest gaps view; the code check on answers; the health check and demo fallback; the decision and cut log.

### 9.5 Risks and day-1 tests

| Risk | Likelihood | Impact | Day-1 test |
|---|---|---|---|
| Graphiti triplet writes misbehave (deduplication, time fields, calls) | Medium | High | Write 20 verified facts as triplets; inspect edges, validity, entity merging and calls made |
| Live run exceeds 5 minutes | Medium | High | Time one full run of the thin slice; record the slowest stage |
| WHO endpoint changed | Medium | Medium | Call current and replacement endpoints for one indicator |
| Authoritative sources unreachable from the host region | Medium | Medium | Fetch a short list of government health sites from the deployed host |
| Services sleep before the demo | High if unmanaged | High | Non-sleeping tiers; health check covers every store |
| Exact quote matching drops too many PDF claims | Medium | Medium | Extract from two real PDF tables; measure the drop rate |
| Front end overruns | High | Medium | Build the City brief screen first; reuse its components |

---

## 10. Vendor neutrality: ports and adapters

Owner requirement: the architecture must not be tied to any paid service, and providers must be easy to switch (R-81, CON-11).

| Port | Default for deployed demo | Free / local adapter | Other adapters |
|---|---|---|---|
| LLM, per agent role | Anthropic (planner, router, extractor, answerer, report writer); OpenAI (checker) | Ollama with an open model | Google, Azure, Groq |
| Embeddings | OpenAI small embedding model `[confirm ID]` | Sentence Transformers (multilingual) | Voyage, Gemini |
| Web search | Brave, links-only | SearXNG, self-hosted | Tavily with content retrieval disabled |
| Relational | Render managed Postgres | Postgres in Docker | Any managed Postgres |
| Vector | Qdrant as Render private service | Qdrant in Docker | Qdrant Cloud |
| Graph | Graphiti on Neo4j Community as Render private service | Neo4j in Docker | AuraDB; other Graphiti backends `[verify driver support]` |
| Snapshots | Table in Postgres | same | S3-compatible storage (MinIO, any bucket) |
| Tracing | Own progress events plus LangSmith free tier | Own events plus OpenTelemetry | Langfuse |
| Structured data | WHO, DHS, World Bank APIs | same (free) | New sources by registry entry |
| Hosting | Render, billed by the second | Docker Compose on any machine | Railway, Fly, a VM, Kubernetes |

**Configuration sketch** (one file per environment; secrets only from environment variables):

```yaml
llm:
  planner:   {provider: anthropic, model: claude-sonnet-5-5}
  extractor: {provider: anthropic, model: claude-haiku-4-5-20251001, escalate_to: claude-sonnet-5-5}
  checker:   {provider: openai,    model: <confirm day 1>, fallback: {provider: anthropic, model: claude-opus-5-5, label: same_family_fallback}}
  answerer:  {provider: anthropic, model: claude-sonnet-5-5}
  reporter:  {provider: anthropic, model: claude-sonnet-5-5}
embeddings:  {provider: openai, model: <confirm day 1>}   # local: sentence_transformers
search:      {provider: brave, mode: links_only}          # local: searxng
vector:      {provider: qdrant, url: http://qdrant:6333}
graph:       {provider: graphiti_neo4j, url: bolt://neo4j:7687}
snapshots:   {provider: postgres}
tracing:     {providers: [events, langsmith]}
```

**Rules enforced in code**
1. Vendor SDKs imported only in the adapters layer; an import-lint test fails the build otherwise (AT-34).
2. Every port has contract tests all adapters must pass (AT-35).
3. Start-up validation: checker family must differ from extractor family unless the labelled fallback is active; no store may mix embedding models (AT-36).
4. Core code never branches on provider names.

**Caveats.** Free local models make the extractor and checker noticeably weaker, which hurts the trust score, so the demo uses the strongest configured models while free adapters are proven by contract tests. "Not tied to a paid service" means portable, not free to run: the public URL (R-09) still needs a host.

---

## 11. Final decisions

| # | Decision | Choice | Rationale |
|---|---|---|---|
| DEC-01 | Hosting for the demo | Render, paid, billed by the second: front end as free static site; API Standard (2 GB); Neo4j Standard and Qdrant Starter as private services with disks; Postgres Basic-256mb | Nothing sleeps (R-09); stores not exposed to the internet; Compose remains the portable default |
| DEC-02 | Run execution | Background task in the API process; events stored in Postgres; replayable stream; checkpointer on; no deploys on demo day | Survives disconnects (R-80); separate worker is production work |
| DEC-03 | Access and spend | One access code; one run at a time; at most 20 runs a day; per run about 60 fetches and 5 minutes; token cap after day-1 measurement; provider-level limits as backup | Protects URL and budget (R-50) |
| DEC-04 | Main models | Sonnet 5.5 (planner, router, answerer, report writer); Haiku 4.5 (extraction) escalating hard documents to Sonnet 5.5 | Quality where judged; one provider for most roles |
| DEC-05 | Fact-checker | OpenAI frontier model `[ID day 1]`; fallback Opus 5.5 labelled "same-family fallback" | Real independence (F8); honest fallback |
| DEC-06 | Embeddings | OpenAI small model deployed; Sentence Transformers locally | Reuses OpenAI key (Voyage dropped); avoids memory pressure on the API instance |
| DEC-07 | Search | Brave, links-only, deployed; SearXNG locally | Self-hosted metasearch is fragile from cloud servers; links-only matches the crawl rule |
| DEC-08 | Tracing | Own progress events always; LangSmith free tier switchable | Walkable trace for DS-2 at no cost |
| DEC-09 | Graph | Graphiti on Neo4j Community; triplet writes; centrality in app | Free, portable, no plugin |
| DEC-10 | Vector | Qdrant in Docker | Free, portable |
| DEC-11 | Snapshots | Postgres table; S3 adapter available | One service fewer |
| DEC-12 | Crawl gate policy | RFC 9309 with error handling; `Content-Usage` opt-outs; login and paywall detection; crawl-delay and `Retry-After`; one request at a time per domain; private-address blocking; honest user-agent; terms-of-use check COULD (stated limit) | Standard-based and defensible (R-03, R-86) |
| DEC-13 | Wave 0 sources | WHO (national, modelled, flagged), DHS (sub-national), World Bank (context) | Honest floor for any city in seconds (R-85) |
| DEC-14 | Health scope | Three risk factors plus stroke and heart-attack outcomes; 16 slots; control rate headline | Matches how the programme reports |
| DEC-15 | "Research" always fresh | Stored cities only via "Open existing"; clear rehearsal cities before the demo | R-01, R-83 |
| DEC-16 | Example report city | Test Hyderabad from the deployed host on day 1; if Indian sources are reachable, use it; otherwise a well-documented city elsewhere, with an Indian city rehearsed as the hard case | Relevant to the role's location, only if strong |
| DEC-17 | Demo format | Plan for 45–60 min with a 30-min version | Unknown until the recruiter confirms |
| DEC-18 | Prepaid credits | About $25 Anthropic, $15 OpenAI; top up after day-1 measurement | Low commitment |
| DEC-19 | Small, high-value additions | Run summary with cost and time per city; trust tests with results in README; graph switch; "Handle with care" list; crawl-decision log | Visible trust and judgment at low cost |
| DEC-20 | Deliberately not built | Maps, voice, chat persona, decorative graph visuals | Restraint is scored |

---

## 12. Cost model

**Hosting (Render list prices, billed by the second):** static front end $0; API Standard $25/month; Neo4j Standard $25/month; Qdrant Starter $7/month; Postgres Basic-256mb $6/month; disks about $0.25 per GB-month. Total about $65–80 a month, so about **$2–3 a day**. Building (3–4 days): under $15. Keeping it live until the demo: about $15–20 a week.

**Variable (estimates, measured day 1):** models about $1–3 per city run; development and rehearsal (40–60 runs) about $40–150; search a few dollars.

**Billing.** Render bills paid services by the second, with no month upfront (a card is needed on file `[check at sign-up]`). Model providers usually work on prepaid credits for individual accounts `[check at sign-up]`.

**Cheaper options.** Build and test locally with Docker Compose (free); use the cloud only for deployment checks and rehearsals. Or free managed tiers plus a scheduled keep-alive, which reintroduces sleep risk.

---

## 13. Open items for the owner

1. Create accounts: Anthropic, OpenAI, Brave Search, Render, LangSmith.
2. Ask the recruiter about the demo format, length, and the gap between submission and demo (Q-12).
3. Day-1 confirmations: OpenAI model IDs; embedding model ID; WHO endpoint; reachability from the host; Brave free-tier limits; PDF library on the host; Graphiti backend support beyond Neo4j.
