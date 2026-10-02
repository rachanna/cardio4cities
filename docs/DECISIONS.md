# Decisions and Cut Log

Every non-trivial decision, with the alternative considered and the reason. The brief scores *how you decide and what you choose not to build*, so this file is a deliverable (R-54), not a side note.

**Rules**
- Add a row before or in the same change as the code it affects.
- Never edit a decided row's meaning. Supersede it with a new row and set the old status to `superseded by <ID>`.
- A change that weakens a MUST requirement needs a row here, approved by the owner, before it is made.

**Statuses:** `decided` · `pending spike` (primary design built, day-1 spike confirms) · `superseded by …`

**ID prefixes:** `DEC` brainstorm decisions · `Δ` changes from the prior design · `HD` high-level design · `LD` data model · `WD` workflow · `PD` prompts · `ID` interfaces · `BD` build (added during build)

---

## 1. Owner-level decisions

| ID | Decision | Alternative | Reason | Status |
|---|---|---|---|---|
| OD-01 | Precision over coverage: an honest gap is a correct output | Maximise coverage | The City Lead repeats facts to officials; a wrong fact costs more than a gap | decided |
| OD-02 | The agent is the system; models are used only where code reaches its limits | Model-led agent with code around it | Testable, auditable, cheaper; see HLD §2.1 | decided |
| OD-03 | Multi-agent with a best-fit model per role, set in configuration | One model for everything | Quality and cost per role; enables a different-family checker | decided |
| OD-04 | Not tied to any paid service; every provider is an adapter | Direct vendor SDK use | Portability; vendor neutrality is an enterprise concern | decided |
| OD-05 | Build on the prior architecture, with the changes Δ1–Δ14 | Start again | Prior design was sound; changes came from research | decided |

## 2. Brainstorm decisions (BRAINSTORM §11)

| ID | Decision | Alternative | Reason | Status |
|---|---|---|---|---|
| DEC-01 | Render, paid, billed by the second; stores as private services with disks | Free tiers with keep-alive | Free tiers sleep or get suspended | decided (hosting of the web app: superseded by ID-01) |
| DEC-02 | Runs as background tasks in the API process; replayable progress; checkpointer on; no deploys on demo day | Separate worker service | Enough for one run at a time | decided |
| DEC-03 | One access code; one run at a time; 20 runs a day; per-run caps | Open URL | Protects the URL and the budget | decided |
| DEC-04 | Sonnet 5.5 for planner, answerer, report writer; Haiku 4.5 for extraction, escalating to Sonnet 5.5 | One model for all | Quality where judged, cost where volume is high | decided |
| DEC-05 | Checker on an OpenAI frontier model; Opus 5.5 as labelled same-family fallback | Same family, higher tier | Different family reduces own-family bias | pending spike (model ID) |
| DEC-06 | OpenAI embeddings deployed; Sentence Transformers locally | Voyage; local model in production | One fewer account; memory on a 2 GB instance | pending spike (model ID) |
| DEC-07 | Brave Search, links only, deployed; SearXNG locally | Tavily; self-hosted search deployed | Metasearch from cloud servers is fragile; links-only matches the crawl rule | decided |
| DEC-08 | Own progress events always; LangSmith free tier switchable | LangSmith required | Walkable trace for the demo without dependence | decided |
| DEC-09 | Graphiti on Neo4j Community; triplet writes; centrality in the app | Episodes; Neo4j analytics plugin | Speed, control, no plugin | pending spike |
| DEC-10 | Qdrant in Docker | pgvector | Three distinct stores | decided |
| DEC-11 | Snapshots in a Postgres table | Object storage | One fewer service | decided |
| DEC-12 | Crawl gate: RFC 9309 with error handling, Content-Usage opt-outs, paywall detection, crawl-delay, private-address blocking, honest user agent | robots only | Standards-based and defensible | decided |
| DEC-13 | Wave 0 from WHO, DHS, World Bank | Web search only | Honest floor for any city in seconds | pending spike (endpoints, codes) |
| DEC-14 | Three risk factors plus stroke and heart-attack outcomes; 16 slots; control rate headline | Broader scope | Matches how the programme reports | decided |
| DEC-15 | "Research" always fresh; stored cities only via "Open existing" | Serve cached results | No-seeding requirement | decided |
| DEC-16 | Test Hyderabad as example city from the deployed host on day 1; fall back if sources are geo-blocked | Fixed choice | Relevant to the role, only if strong | pending spike |
| DEC-17 | Plan the demo for 45–60 minutes with a 30-minute version | Single plan | Format unknown | decided |
| DEC-18 | Prepaid credits about $25 Anthropic, $15 OpenAI | Larger commitment | Measure first | decided |
| DEC-19 | Run summary with cost and time; trust tests in README; graph switch; handle-with-care list; crawl log | — | Visible trust and judgment at low cost | decided |
| DEC-20 | Not built: maps, voice, chat persona, decorative graph visuals | Build them | Restraint is scored | decided |

## 3. Changes from the prior design

| ID | Change | Reason |
|---|---|---|
| Δ1 | Verified facts written to Graphiti as triplets, not episodes | Episodes are slow and re-extract with a model |
| Δ2 | Statistic values live in Postgres; the graph links them | Graph contradiction handling would wrongly supersede numbers |
| Δ3 | Centrality computed in the app | Neo4j analytics plugin unavailable on free tiers |
| Δ4 | Generic country-keyed structured sources first | Floor of data for any city |
| Δ5 | Crawl gate honours Content-Usage opt-outs | Emerging standard, cheap to honour |
| Δ6 | Day-1 check of the WHO endpoint | API was being replaced |
| Δ7 | Non-sleeping services, health check, keep-alive | Free tiers sleep |
| Δ8 | Links-only search | Vendor extraction would bypass the gate |
| Δ9 | Plan for about 1 search per second | Free-tier rate limits |
| Δ10 | Background runs with replayable events | Redeploys and dropped connections |
| Δ11 | Consistency check in code | Fewer model calls; deterministic |
| Δ12 | Snapshots inside Postgres | One fewer service |
| Δ13 | Concise ARCHITECTURE.md separate from build docs | Two audiences |
| Δ14 | Ports and adapters | OD-04 |

## 4. High-level design (HLD §16)

| ID | Decision | Alternative | Reason | Status |
|---|---|---|---|---|
| HD-01 | Run-level stage plus per-slot subgraph in parallel; shared fetch cache | Linear pipeline | Parallelism inside the time budget | decided |
| HD-02 | Ambiguous names resolved before the run | Inside the run | User confirms identity | decided |
| HD-03 | Structured-source claims verified by code against the stored record | Model checker | Deterministic data is better checked by code | decided |
| HD-04 | Source selection in code | Model router | Deterministic, cheaper | decided |
| HD-05 | Gap notes from templates | Model-written | Gaps are factual records | decided |
| HD-06 | Our resolver assigns entity IDs before graph writes | Graphiti resolves | Auditable; fewer model calls | pending spike |
| HD-07 | Report assembled by code; model writes linking prose only | Model-written report | No new facts can enter | decided |
| HD-08 | Low-confidence facts excluded from the executive summary | Show everything | Confidence must change behaviour | decided |
| HD-09 | Events written before streaming, with sequence numbers | In-memory stream | Replay after disconnect | decided |
| HD-10 | Static web export, served by the API on the same origin | Server-rendered app | One fewer service | decided (hosting revised by ID-01) |
| HD-11 | Small fast model for question classification | Larger model | Narrow task; latency | decided |

## 5. Data model (LLD-1 §10)

| ID | Decision | Alternative | Reason | Status |
|---|---|---|---|---|
| LD-01 | Prefixed ULIDs as IDs | UUIDv4 | Sortable, readable | decided |
| LD-02 | One source row per URL per run | Shared global sources | Evidence ties to what this run saw | decided |
| LD-03 | Required labels as columns, optional as JSONB | All JSONB | Required labels are filtered and indexed | decided |
| LD-04 | Numbers parsed by code from the written value | Model returns the number | Models must not produce numbers | decided |
| LD-05 | Badges and confidence computed at read time | Stored | Tunable without migrations | decided |
| LD-06 | Entity identity owned by Postgres; graph UUIDs derived | Graphiti identity | Auditable; supports purge | decided |
| LD-07 | Vector collection name includes the embedding key | One collection | Models can never mix | decided |
| LD-08 | Policy slots accept national evidence; statistic slots never do | Same rule | Policy lives nationally; prevalence does not | decided |

## 6. Workflow (LLD-2 §19)

| ID | Decision | Alternative | Reason | Status |
|---|---|---|---|---|
| WD-01 | Budget in a process-level ledger | In graph state | Parallel branches would race | decided |
| WD-02 | Routing edges at slot level | Edge per URL or claim | Visible, testable | decided |
| WD-03 | A statistic's value must appear inside its quote | Anywhere in source | Ties the number to the checked passage | decided |
| WD-04 | Ranges never collapsed to a midpoint | Midpoint | A computed number appears in no source | decided |
| WD-05 | Different reference periods are a series, not a conflict | Flag all differences | Avoids false disagreement | decided |
| WD-06 | Wider-area statistic slots get one re-plan | None or two | One more try without burning budget | decided |
| WD-07 | robots.txt 5xx reported as unreachable | Blocked | Honest reason | decided |
| WD-08 | People never merged by embedding similarity | Merge | Merging two people is worse than a duplicate | decided |
| WD-09 | Confidence and badges at read time | Stored | Same as LD-05 | decided |

## 7. Prompts (LLD-3 §10)

| ID | Decision | Alternative | Reason | Status |
|---|---|---|---|---|
| PD-01 | Structured output enforced by the adapter | JSON instructions in prompts | Fewer format failures; provider-neutral prompts | decided |
| PD-02 | Examples use a fictional city and country | Real examples | Prompts cannot seed city data | decided |
| PD-03 | Checker "supported" with any issue is downgraded by code | Trust the label | Inconsistent verdicts never create facts | decided |
| PD-04 | Abstention wording from stored gap records | Model writes it | Shows exactly what was searched | decided |
| PD-05 | One extraction per source for all slots that selected it | Per source per slot | Halves extraction calls | decided |
| PD-06 | Checker sees ±600 characters around the quote | Whole source | Focused judgment; clearer independence | decided |

## 8. Interfaces (LLD-4 §13)

| ID | Decision | Alternative | Reason | Status |
|---|---|---|---|---|
| ID-01 | API serves the web app on the same origin | Separate static site | Cookie works for the event stream; no CORS; one fewer service | decided |
| ID-02 | Cookie session from an access code | Header on each request | Event streams cannot send custom headers | decided |
| ID-03 | Event stream replays from Postgres, then polls | Memory only | Correct after reconnects and restarts | decided |
| ID-04 | Postgres repositories are the relational port | Generic interface | Postgres is fixed | decided |
| ID-05 | Paid-provider health checks cached 10 minutes | Live each call | Keep-alive must not spend budget | decided |
| ID-06 | Stored HTML snapshots served sandboxed | As-is | Stored pages must not run scripts | decided |

## 9. Build decisions

Added during the build as `BD-01`, `BD-02`… Spike results go here first.

| ID | Decision | Alternative | Reason | Status |
|---|---|---|---|---|
| | | | | |

---

## 10. Cut list (what we chose not to build)

| Cut | Why | What would bring it back |
|---|---|---|
| Trained entity-resolution and confidence models | No time to label data | Labelled pairs from real runs |
| Human review before storage | Autonomy is the point; flags and post-hoc review cover the risk | Production use with high-stakes exports |
| Accounts, roles, collaboration | Single demo audience | Multi-team rollout |
| Cross-city comparison screen | Data model supports it; not needed for the demo | A second city in production |
| Scheduled refresh and change alerts | Temporal model supports it | Ongoing programme use |
| Headless browser for script-rendered pages | Weight and failure modes; unreadable pages recorded honestly | Measured share of unreadable sources |
| OCR of scanned PDFs | Time | Measured false-gap rate |
| Terms-of-use page checking in the crawl gate | Time; stated as a limit | Legal review of target domains |
| Paywalled, login-protected, social media sources | Not permitted or not reliable | Licensed access |
| Search-vendor content extraction | Would bypass the crawl gate | Never |
| Neo4j analytics plugin | Not on free tiers; app computes centrality | Paid graph tier |
| Separate worker service | One run at a time is enough | Concurrent production use |
| Age standardisation | Method metadata shown instead | An epidemiologist on the team |
| Maps, voice, chat persona, decorative graph views | Do not serve the City Lead's decision | Never for this purpose |

Cut order if time runs short, and what is never cut: `BRAINSTORM.md` §9.3–9.4.
