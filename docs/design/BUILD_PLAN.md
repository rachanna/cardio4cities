# Build Plan

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-10-02 |
| **Timebox** | 4 working days including design (CON-01); design is complete |
| **Inputs** | All of `docs/design/`, `docs/DECISIONS.md` |

**How to use this plan with Claude Code.** Each task below is sized for one Claude Code session. Start the session by naming the task ID; the **Load** column lists the documents to read for that task, beyond `CLAUDE.md`. A task is finished only when its **Done when** checks pass. Record spike outcomes and any deviation as `BD-` rows in `DECISIONS.md` before moving on.

**Principles**
1. Spikes first: anything that can change the design is tested on day 1.
2. Deploy on day 1: the URL must work long before the demo.
3. One thin slice end to end before breadth: one slot, one source, one verified fact, one cited answer.
4. Tests with the code: every rule ships with its unit tests; every task closes the acceptance tests it names.
5. When a day ends behind, cut by the order in §6, never by weakening a MUST.

---

## 0. Before day 1 (owner)

| # | Task | Notes |
|---|---|---|
| O-1 | Create accounts and keys: Anthropic, OpenAI, Brave Search, Render, LangSmith | Prepaid credits about $25 and $15 (DEC-18); set provider-level monthly limits |
| O-2 | Set up git and the GitHub repository | Follow `docs/GIT.md` §1–5: `.gitignore` first, design pack committed, secret scanning on |
| O-3 | Ask the recruiter: demo format, length, and gap between submission and demo | Drives the keep-alive window and the run sheet (Q-12) |
| O-4 | Choose the access code and admin code | At least 12 characters; never committed |

---

## 1. Day 1: foundations, spikes, deployed skeleton

| ID | Task | Load | Outputs | Done when | Est. |
|---|---|---|---|---|---|
| D1-1 | Repository scaffold | REPO_STRUCTURE | Layout, `pyproject.toml`, Makefile, Dockerfile, compose, `.env.example`, empty packages, CI running lint and tests | `make up`, `make lint`, `make test` succeed on an empty suite | 1 h |
| D1-2 | Ports, config and validation | LLD-4 §5, §8 | Protocols; config loader; start-up validation; `container.py` | AT-36 passes; import-linter contracts active (AT-34) | 1 h |
| D1-3 | Database and reference data | LLD-1 §3–4 | Alembic migrations for all tables and views; loaders for GeoNames and the YAML reference files | `make migrate reference` loads 16 slots and the gazetteer; AT-02 scan runs | 1.5 h |
| D1-4 | Deployed skeleton | REPO_STRUCTURE §5, LLD-4 §3.1, §7 | `render.yaml`; app with session and `/health` touching Postgres, Qdrant, Neo4j; static placeholder page at `/` | Deployed URL serves `/` and `/api/v1/health` returns `ok` from outside (AT-29 partial) | 1 h |
| D1-5 | Spikes (§2) | §2 below, LLD-1 §6.3 | Six spike scripts with written results | Each spike has a recorded outcome and a `BD-` row | 2.5 h |

**Day 1 exit check:** URL live with all stores reachable; spike results recorded; reference data loaded; CI green.

---

## 2. Day-1 spikes

| Spike | Script | Pass when | If it fails |
|---|---|---|---|
| S-1 Graphiti triplets | `spikes/graphiti_triplets.py` | 20 triplets written with our UUIDs; no Graphiti entity re-resolution; edge attributes returned by search; `invalid_at` set without deletion; model calls counted | Fallback in LLD-1 §6.3 (episode per source); record BD row; DEC-09 and HD-06 updated |
| S-2 WHO and DHS endpoints | `spikes/who_endpoint.py` | Hypertension prevalence and control codes return records for three countries; DHS returns a sub-national record for one | Use the replacement WHO API; or Wave 0 from DHS and World Bank only |
| S-3 Reachability from the host | `spikes/reachability.py` (run on the deployed service) | WHO, DHS, World Bank APIs reachable; record which of a list of government health sites (India and two other countries) return content | Decide the example city (DEC-16); `unreachable` stays honest |
| S-4 Search links only | `spikes/search_links_only.py` | Brave returns title, URL, snippet with no page content; rate limits observed | Switch adapter; adjust Δ9 timing |
| S-5 PDF quote matching | `spikes/pdf_quotes.py` | On two real PDF tables, extraction plus §4.1 matching drops under about 20% of claims | Improve normalisation and table parsing; never loosen matching |
| S-6 Run timing | `spikes/run_timing.py` (after D2-3; may slip to day 2) | One slot end to end under 60 s; projected full run under 5 min | Reduce slots per round, claims verified per slot, or URLs per slot |

Also confirm on day 1: the OpenAI checker and embedding model IDs and the embedding dimension (fill `deployed.yaml`), and WeasyPrint in the image.

---

## 3. Day 2: the research workflow, thin slice first

| ID | Task | Load | Outputs | Done when | Est. |
|---|---|---|---|---|---|
| D2-1 | Domain rules | LLD-1 §1–2, LLD-2 §4–8 | `domain/` and `workflow/rules/`: quotes, numbers, thresholds, comparability, ranking, consistency, confidence, badges, slot status, gap notes | All unit tests from LLD-2 §4–§11 pass; AT-09, AT-21, AT-31 | 2 h |
| D2-2 | Collection | LLD-2 §9, §14 | Crawl gate, robots and Content-Usage parsing, pinned-IP fetcher, HTML and PDF parsing, chunking and embedding, snapshots, selection | AT-04, AT-05, AT-06, AT-23, AT-33 against a local test server | 2 h |
| D2-3 | **Thin slice** | LLD-2 §3, LLD-3 §3–5 | Graph with resolve, plan (one slot), search, select, gate, fetch, extract, match, verify, write to Postgres and Qdrant; events stored and streamed | One real city, slot S04: at least one verified, cited claim in Postgres; events replayable (AT-30); AT-07, AT-08 | 2 h |
| D2-4 | Graph and entities | LLD-1 §6, LLD-2 §5.5, §6 | Entity resolution; Graphiti writes per S-1 outcome; supersession and contested relations | AT-26; a GOVERNS edge written and readable with its claim ID | 1.5 h |
| D2-5 | Breadth | LLD-2 §3, §11–13 | All 16 slots in parallel, Wave 0, coverage loop and re-plans, budget ledger, run summary | A full run on one real city ends under 5 min with every slot carrying a status; AT-16, AT-19, AT-32, AT-38 | 1.5 h |

**Day 2 exit check:** one real city researched end to end on the deployed URL from the command line or API; every slot has a status; verified facts in all three stores.

**Cut trigger:** if D2-3 is not done by midday, defer D2-4 entity merge by embedding (keep normalised and acronym steps) and drop to 10 slots for D2-5.

---

## 4. Day 3: answering, report, interface, deployment

| ID | Task | Load | Outputs | Done when | Est. |
|---|---|---|---|---|---|
| D3-1 | Read API | LLD-4 §2–3, LLD-1 §4.6, §7 | Brief, findings, entities, evidence, snapshots, cities, runs endpoints | AT-12, AT-25, AT-27, AT-37 | 1.5 h |
| D3-2 | Question answering | LLD-2 §15, LLD-3 §6–7 | Classifier, retrieval by type, bundle, answerer, post-check, abstentions, graph switch | AT-10, AT-11, AT-15, AT-28 | 2 h |
| D3-3 | Report | LLD-2 §16, LLD-3 §8 | Assembly, templates, PDF | AT-18 | 1 h |
| D3-4 | Web app | HLD §12, LLD-4 §12 | Access, Start with live progress and coverage grid, City brief, Explore, Ask, Evidence panel; admin overlay | A non-technical walk-through works on a phone and a laptop; City brief screen built first | 3 h |
| D3-5 | Deploy and smoke | REPO_STRUCTURE §5 | Full deploy; keep-alive job | AT-17, AT-29 from outside; full run on the deployed URL | 0.5 h |

**Day 3 exit check:** a user can open the URL, research a city, explore, ask, trace evidence and download a report.

**Cut trigger:** if D3-4 overruns, keep City brief, Ask and the Evidence panel; reduce Explore to a filtered list without the entity network view.

---

## 5. Day 4: trust, hardening, deliverables, rehearsal

| ID | Task | Load | Outputs | Done when | Est. |
|---|---|---|---|---|---|
| D4-1 | Trust tests and planted cases | HLD §9.5, LLD-3 §9 | Planted cases as tests and as admin endpoint; golden-set run; results in README | AT-20, AT-22; golden pass bar met | 1.5 h |
| D4-2 | Hardening | LLD-2 §17 | Retries, fallback checker, graph-write retry, error messages | A run with one provider failing still ends with statuses | 1 h |
| D4-3 | Example output | DEC-16 | Report from the deployed system in `samples/` with run ID and date | Unedited, complete | 0.5 h |
| D4-4 | ARCHITECTURE.md and README | R-19, R-20 | Concise architecture for the panel; README with URL, access, quick start, trust-test results | Covers components, agents, data, retrieval, trade-offs, DQ answers | 1 h |
| D4-5 | Deck | BRAINSTORM §8 | 7 slides | Exported into `deck/` | 1 h |
| D4-6 | Rehearsals | `docs/REHEARSAL.md` | Two full rehearsals on the deployed URL | Both pass; issues fixed or recorded as limits | 1.5 h |
| D4-7 | Freeze | R-91 | Purge rehearsal cities except the fallback; auto-deploy off | Health check passes; definition of done met (REQUIREMENTS §19) | 0.5 h |

---

## 6. When time runs short

Cut in this order (BRAINSTORM §9.3), recording each cut in `DECISIONS.md` §10:

1. All COULD items (analytics, review list, change view, gap research from chat, crash resume, second example report)
2. Entity network view (entity pages stay as lists)
3. Local-language queries
4. Different-family checker (keep the isolated checker; record the limit)
5. Entity merge by embedding
6. Report styling (Markdown and plain PDF stay)
7. Slots reduced to about 10, keeping S04

**Never cut:** the nine non-negotiables; exact quote matching; checker consequences; the gaps view; the answer post-check; the health check and fallback city; this decision log.

---

## 7. Daily rhythm

| When | What |
|---|---|
| Start of day | Re-read this plan; check yesterday's exit; decide cuts if behind |
| Each task | One Claude Code session; tests with the code; commit when green |
| Midday | Check the day's cut trigger |
| End of day | Deploy; run the smoke tests; update `DECISIONS.md`; note tomorrow's first task |

---

## 8. Owner tasks during the build

| When | Task |
|---|---|
| Day 1 | Watch the spike results; approve any `BD-` decision that changes the design |
| Day 2 | Pick the rehearsal cities: one sparse, one non-English, one ambiguous name, the three pioneer cities |
| Day 3 | Walk the interface as a City Lead; note anything confusing |
| Day 4 | Rehearse twice; one rehearsal with a city chosen by someone else |
| Demo day | Health check an hour before; no deploys |
