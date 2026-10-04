# Repository Structure

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-10-02 |
| **Inputs** | HLD v1.0 · LLD-1 to LLD-4 v1.0 |

**For Claude Code.** Create files where this document says. A new top-level folder or a change to the dependency rules (§3) needs a `BD-` entry in `docs/DECISIONS.md`.

---

## 1. Layout

Files marked *(not built)* are planned and have no file yet; *(Dn-n)* names the task that adds them (BD-36; code review §9).

```text
cardio4cities/
├── CLAUDE.md                     # read first, every session
├── README.md                     # URL, access, quick start, architecture summary, trust-test results
├── pyproject.toml                # Python deps, ruff, mypy, pytest, import-linter contracts, poe tasks (§4)
├── uv.lock
├── .python-version               # 3.12 (uv)
├── .gitattributes                # * text=auto eol=lf (BD-01)
├── .pre-commit-config.yaml       # gitleaks, ruff, import-linter
├── .github/workflows/ci.yml      # lint and tests, secret scan, image build; actions pinned to SHAs (BD-36)
├── Dockerfile                    # Python image; the web build stage arrives with D3-4
├── .dockerignore
├── docker-compose.yml            # local: postgres, qdrant, neo4j, searxng, app
├── render.yaml                   # deployed: web service, private services, Postgres, keep-alive job
├── .env.example                  # LLD-4 §5.3
├── .gitignore                    # .env, reference/geonames/*.txt, node_modules, .next, out
│
├── config/                       # keys exactly as LLD-4 §5.1, plus BD-02 additions
│   ├── searxng/settings.yml      # local SearXNG: JSON output, limiter off (BD-01)
│   ├── local.yaml                # LLD-4 §5.1, local adapters, low-cost models (BD-05)
│   ├── local-quality.yaml        # local.yaml with the deployed model bindings (APP_ENV=local-quality)
│   ├── local-openai.yaml         # OpenAI-only development profile, labelled same-family checker (BD-23)
│   └── deployed.yaml             # LLD-4 §5.1, deployed adapters
│
├── reference/                    # generic reference data only: never city facts (A-09, AT-02)
│   ├── slots.yaml                # LLD-1 §3.2
│   ├── indicators.yaml           # LLD-1 §3.3
│   ├── thresholds.yaml           # LLD-2 §4.3
│   ├── sources.yaml              # LLD-1 §3.4 (Wave 0 registry)
│   ├── publishers.yaml           # LLD-2 §14 (domain patterns, deny list)
│   ├── region_aliases.yaml       # LLD-2 §13 (generic admin-1 name aliases)
│   ├── keyword_stopwords.yaml    # LLD-5 §4.1 keyword route (BD-36, BD-38)
│   └── geonames/README.md        # download instructions; dumps are git-ignored
│
├── app/
│   ├── main.py                   # FastAPI app factory; mounts /api/v1 and serves web/out at / (ID-01)
│   ├── settings.py               # config loading and start-up validation (LLD-4 §5.2)
│   ├── container.py              # builds adapters from config and wires them into services
│   ├── api/
│   │   ├── routers/              # session, cities, runs, events, facts, snapshots, ask, reports, health, workflow, admin
│   │   ├── schemas.py            # request/response models (LLD-4 §2–3)
│   │   ├── auth.py               # session cookie, roles
│   │   ├── limits.py             # rate limits
│   │   └── errors.py             # error envelope (LLD-4 §6)
│   ├── domain/                   # pure: no I/O, no vendor imports
│   │   ├── vocab.py              # enums (LLD-1 §1)
│   │   ├── models.py             # types (LLD-1 §2)
│   │   ├── ranking.py            # LLD-2 §5.2
│   │   ├── confidence.py         # LLD-2 §7
│   │   ├── badges.py             # LLD-2 §8
│   │   ├── wording.py            # user-facing vocabulary (R-90)
│   │   ├── params.py             # tunables passed into the rules, built from config (BD-06)
│   │   ├── dates.py              # calendar arithmetic; `today` is always passed in
│   │   ├── geography.py          # effective geography level of a claim
│   │   ├── place_names.py        # name keys shared by claims and the gazetteer (BD-17)
│   │   ├── text.py               # quote normalisation, LLD-2 §4.1 (BD-38)
│   │   ├── entity_names.py       # entity name keys and acronyms (BD-38)
│   │   ├── cards.py              # FactCard, SlotRow (BD-37)
│   │   ├── charset.py            # text decoding rules
│   │   ├── prices.py             # model and embedding prices (BD-30)
│   │   └── ids.py                # deterministic uuid5 IDs (Qdrant points, graph nodes)
│   ├── workflow/
│   │   ├── graph.py              # main graph and slot subgraph (LLD-2 §3)
│   │   ├── state.py              # RunState, SlotState
│   │   ├── runner.py             # run manager: start, background task, resume; ports via RunPorts (BD-09)
│   │   ├── deps.py               # RunDeps: ports and parameters passed to nodes in the run config (BD-09)
│   │   ├── llm.py                # call a model role: reserve, repair once, checker fallback (LLD-2 §17)
│   │   ├── entities.py           # entity resolver: alias, acronym, key, embedding, new (LLD-2 §6, BD-12)
│   │   ├── graph_writes.py       # one edge per supported claim; supersession as invalid_at (BD-12)
│   │   ├── claim_index.py        # set_status: Postgres, then search_tsv and the claim index (CHG-01)
│   │   ├── budget.py             # BudgetLedger: wind-down, warnings, restore (LLD-2 §12, BD-14)
│   │   ├── limits.py             # run-wide model and embedding concurrency; StageClock (BD-14)
│   │   ├── fetch_cache.py        # one fetch per URL per run, shared by slots (LLD-2 §14, BD-14)
│   │   ├── events.py             # EventEmitter (LLD-2 §10)
│   │   ├── collection.py         # Collector: gate, pinned fetch, parse for one URL (LLD-2 §9, BD-07)
│   │   ├── ids.py                # prefixed ULIDs; content-derived stable_id for replay (BD-14)
│   │   ├── nodes/                # one file per node
│   │   └── rules/                # pure: crawl_gate, robots, content_usage, selection, chunking, quotes,
│   │                             #       numbers, thresholds, comparability, consistency,
│   │                             #       entity_resolution, slot_status, gap_notes, wave0_record,
│   │                             #       labels (reference-period rule, derived flags), label_evidence,
│   │                             #       geography_fit, programme_status, region_match,
│   │                             #       other_places (source selection, BD-15)
│   ├── query/                    # LLD-5 (CHG-01, BD-38): understand.py, routes/ (structured.py, keyword.py,
│   │                             #   semantic.py, graph.py), revalidate.py, fuse.py (fusion, anchors),
│   │                             #   bundle.py, postcheck.py, pipeline.py, llm.py, types.py
│   ├── report/                   # assemble.py, render.py, templates/report.{md,html}.j2 (LLD-2 §16, BD-40)
│   ├── prompts/
│   │   ├── loader.py             # loads text, computes prompt_version (LLD-3 §2.5)
│   │   ├── safety.py             # <source> wrapping and escaping (LLD-3 §2.2)
│   │   └── <role>/v1.md, schema.py   # planner, extractor, checker, classifier, answerer, reporter
│   ├── ports/                    # Protocols (LLD-4 §8), one module per port with its value types; errors.py, health.py
│   └── adapters/                 # the ONLY place vendor SDKs are imported
│       ├── llm/                  # anthropic.py, openai.py; ollama.py (not built)
│       ├── embeddings/           # openai.py, sentence_transformers.py
│       ├── search/               # brave.py, searxng.py, _common.py (rate limit); tavily.py (not built)
│       ├── fetch/                # httpx_pinned.py (IP-pinned, httpx: BD-07), robots_protego.py
│       ├── parse/                # documents.py: trafilatura (HTML, table spans expanded with lxml), pdfplumber (PDF) (BD-07, BD-10)
│       ├── structured/           # who_gho.py, world_bank.py: pure URL building and parsing (BD-13)
│       ├── vector/               # qdrant.py, qdrant_probe.py
│       ├── graph/                # graphiti.py (direct-save path, BD-11), neo4j_probe.py
│       ├── snapshots/            # postgres.py
│       ├── renderer/             # fpdf2.py and fonts/ (DejaVu, open licence) (BD-40); browser_print.py (not built)
│       ├── tracing/              # events are written by the workflow; langsmith.py, otel.py (not built, BD-36)
│       └── postgres/             # db.py, relational.py, repos/, migrations/ (Alembic), checkpointer.py
│
├── web/                          # (D3-4) Next.js, static export to web/out; web/placeholder until then
│   ├── app/                      # routes: / (access + start), /city/[id], /city/[id]/explore, /city/[id]/ask
│   ├── components/               # FactCard, Badge, ConfidenceReasons, CoverageGrid, EvidencePanel,
│   │                             # ProgressStream, EntityPage, EntityNeighbours, AnswerView, AdminOverlay
│   ├── lib/api.ts                # client; types generated from OpenAPI (web/lib/api-types.ts)
│   └── styles/
│
├── scripts/
│   ├── reference/                # load_geonames.py, load_yaml_reference.py
│   ├── spikes/                   # graphiti_triplets.py (S-1), structured_endpoints.py (S-2),
│   │                             # reachability.py (S-3, BD-36), brave_links.py (S-4),
│   │                             # pdf_quotes.py (S-5), full_run.py and compare_runs.py (S-6),
│   │                             # thin_slice.py (D2-3 live check; city typed at run time);
│   │                             # replay_source.py (BD-10: re-run a stored source, no web);
│   │                             # outputs naming real
│   │                             # places go to the git-ignored spike_results/
│   │                             # results/ holds each spike's written outcome
│   ├── purge_city.py             # (D3-5) LLD-1 §8, LangGraph checkpoints included (BD-36)
│   ├── purge_graph.py            # local only: empty Neo4j, its marker and the graph links (BD-14, BD-36)
│   ├── eval_prompts.py           # LLD-3 §9
│   ├── eval_answers.py           # classifier and answerer golden sets (BD-38)
│   ├── eval_rag.py               # retrieval evaluation, `poe eval-rag` (LLD-5 §12, BD-39)
│   ├── predeploy.sh, start.sh    # Render pre-deploy (migrations, reference data) and start
│   └── keepalive.sh              # calls /api/v1/health
│
├── tests/
│   ├── unit/                     # rules and domain
│   ├── contract/                 # one module per port (AT-35)
│   ├── acceptance/               # AT map, LLD-4 §11
│   ├── architecture/             # import-lint (AT-34), purity of domain and rules
│   ├── support/                  # webworld.py: local fictional web for gate and fetch tests
│   ├── smoke/                    # deployed URL (AT-17, AT-29)
│   ├── prompts/golden/           # fictional snippets and expected outputs; results/ per profile (BD-10)
│   └── fixtures/                 # fictional city "Halden Bay, Norvania"; recorded provider responses;
│                                 # retrieval/halden_bay/: claims, entities, edges, questions with gold answers (CHG-01)
│
├── docs/
│   ├── ARCHITECTURE.md           # concise, for the panel (R-20)
│   ├── DECISIONS.md
│   ├── REHEARSAL.md
│   ├── no_seeding_allowlist.yaml # reviewed place names in docs/ for the AT-02 scan (BD-35)
│   └── design/                   # REQUIREMENTS, BRAINSTORM, HLD, LLD-1..4, REPO_STRUCTURE, BUILD_PLAN
├── deck/                         # exported slides (R-22)
└── samples/                      # example report from the deployed system (R-21)
```

---

## 2. Tooling

| Area | Choice |
|---|---|
| Python | 3.12, managed with `uv` |
| Web framework | FastAPI, Uvicorn |
| Workflow | LangGraph, `langgraph-checkpoint-postgres` |
| Database access | SQLAlchemy Core (async) with asyncpg; Alembic migrations |
| Validation | Pydantic v2 |
| Quality | ruff (lint and format), mypy (strict on `app/domain` and `app/workflow/rules`), pytest with pytest-asyncio |
| Architecture checks | import-linter contracts in `pyproject.toml` |
| Front end | Node 20, pnpm, Next.js with `output: 'export'`, TypeScript, `openapi-typescript` for API types |
| Containers | One application image; official images for Postgres 16, Qdrant, Neo4j 5 Community, SearXNG |

Libraries named in the LLD with `[verify]` (Protego, trafilatura, pdfplumber, WeasyPrint, graphiti-core, python-ulid) are confirmed on day 1 and pinned in `uv.lock`.

---

## 3. Dependency rules (enforced, AT-34)

```text
api      → workflow, query, report, domain, ports
workflow → domain, ports, prompts            (langgraph allowed)
query    → domain, ports, prompts
report   → domain, ports, prompts            (jinja2 allowed)
prompts  → domain
domain   → nothing in app
ports    → domain
adapters → ports, domain                     (vendor SDKs allowed only here)
container, main → everything                 (composition root)
```

The fetch adapter uses `httpx`, chosen over `httpx2` for the security-critical path (BD-07); `httpx2` is a test-only dependency.

**Vendor packages allowed only under `app/adapters/`:** `anthropic`, `openai`, `ollama`, `sentence_transformers`, `qdrant_client`, `graphiti_core`, `neo4j`, `httpx`, `httpx2`, `httpcore`, `httpcore2`, `protego`, `trafilatura`, `lxml`, `pdfplumber`, `weasyprint`, `fpdf` (PDF rendering, BD-40), `langsmith`, `opentelemetry`, `asyncpg`, `sqlalchemy`, `alembic`, `psycopg`, `psycopg_pool` (the LangGraph checkpointer's driver, BD-14), `cryptography` (reading a certificate's issuer URL, BD-15; verifying a completed chain, BD-16), `certifi` (the trusted roots for that check, BD-16).

Expressed as import-linter `layers` and `forbidden` contracts. The architecture test fails the build on any violation.

---

## 4. Commands (poe tasks, BD-01)

Run as `uv run poe <task>`; tasks are defined in `pyproject.toml` under `[tool.poe.tasks]`.

| Command | Does |
|---|---|
| `poe up` | Start local stores and SearXNG with Docker Compose |
| `poe migrate` | Run Alembic migrations; needs `DATABASE_URL` only |
| `poe reference` | Download GeoNames (if missing) and load all reference data; needs `DATABASE_URL` only |
| `poe geonames` | Download GeoNames only (the AT-02 scan reads it) |
| `poe dev` | API with reload on :8000, plus `web` dev server on :3000 proxying `/api` (added by D3-4) |
| `poe web` | Build the static export into `web/out` (added by D3-4) |
| `poe test` | Unit, contract, architecture and acceptance tests (recorded responses) |
| `poe lint` | ruff, mypy, import-linter |
| `poe fmt` | ruff format and auto-fix |
| `poe down` | Stop local stores |
| `poe types` | Regenerate `web/lib/api-types.ts` from the OpenAPI document (added by D3-4) |
| `poe spike NAME` | Run one script in `scripts/spikes/` |
| `poe eval` | Prompt golden set against real models (costs money) |
| `poe eval-rag` | Retrieval evaluation with real models (costs money; ask the owner first; CHG-01, BD-39); `--real FILE` for a researched city |
| `poe smoke URL` | Smoke tests against a deployed URL |
| `poe purge CITY` | Remove a city from all stores, its LangGraph checkpoints (`lg`) included (added by D3-5, BD-36) |
| `poe purge-graph` | Delete the local Neo4j graph, its embedding marker and the Postgres graph links; refuses a graph not on this machine and `APP_ENV=deployed` (BD-14, BD-36) |

---

## 5. Deployment files

**Dockerfile** (multi-stage): stage 1 builds `web/out` with Node (D3-4; until then FastAPI serves `web/placeholder`); stage 2 is a slim Python 3.12 image with system libraries for WeasyPrint `[verify]`, installs with `uv`, downloads GeoNames during the build, and copies `app/`, `config/`, `reference/*.yaml`, `scripts/reference` and the web files. The start command (`scripts/start.sh`) runs Uvicorn only; migrations and reference loading run as Render's pre-deploy command (`scripts/predeploy.sh`) (BD-04).

**render.yaml** (blueprint; all services in `singapore`; plan IDs are Render's compute plans, BD-04):

| Service | Type | Plan | Notes |
|---|---|---|---|
| `c4c-app` | Web service, Docker | `1c-2g` (2 GB) | Health check path `/api/v1/health`; pre-deploy `scripts/predeploy.sh`; auto-deploy off (R-91) |
| `c4c-neo4j` | Private service, image `neo4j:5.26.31-community` | `1c-2g` (2 GB) | 5 GB disk at `/data`; heap 1 GB, page cache 512 MB as in compose |
| `c4c-qdrant` | Private service, image `qdrant/qdrant:v1.19.1` | `0.5c-512mb` | 5 GB disk at `/qdrant/storage`; API key required |
| `c4c-db` | Managed Postgres 16 | `basic-256mb` | Private network only |
| `c4c-keepalive` | Cron job, image `curlimages/curl`, every 6 hours | `0.5c-512mb` | Calls `/api/v1/health`; `scripts/keepalive.sh` is the same request for manual use |

Auto-deploy is off so nothing redeploys during rehearsals or the demo. Store credentials live in the env group `c4c-stores` with a `STORE_` prefix, because the Neo4j image treats every `NEO4J_*` variable as a setting.

**docker-compose.yml** mirrors the same services locally, plus SearXNG, with no keep-alive job.

---

## 6. Naming conventions

| Thing | Convention |
|---|---|
| Python modules | `snake_case`; one node per file in `workflow/nodes/` named after the node |
| Tests | `test_<unit>.py`; acceptance tests named after the behaviour, with the AT ID in the docstring |
| Prompt files | `app/prompts/<role>/v<n>.md`; a new version is a new file, never an edit of an old one |
| Migrations | Alembic autogenerate is off; hand-written, named `NNNN_<summary>.py` |
| Config keys | Exactly as LLD-4 §5.1 |
| Branches | `day1/<task>`, `day2/<task>`… merged to `main` when tests pass |
