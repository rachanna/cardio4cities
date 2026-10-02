# Repository Structure

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-10-02 |
| **Inputs** | HLD v1.0 · LLD-1 to LLD-4 v1.0 |

**For Claude Code.** Create files where this document says. A new top-level folder or a change to the dependency rules (§3) needs a `BD-` entry in `docs/DECISIONS.md`.

---

## 1. Layout

```text
cardio4cities/
├── CLAUDE.md                     # read first, every session
├── README.md                     # URL, access, quick start, architecture summary, trust-test results
├── pyproject.toml                # Python deps, ruff, mypy, pytest, import-linter contracts, poe tasks (§4)
├── uv.lock
├── .python-version               # 3.12 (uv)
├── .gitattributes                # * text=auto eol=lf (BD-01)
├── .pre-commit-config.yaml       # gitleaks, ruff, import-linter
├── .github/workflows/ci.yml      # lint and tests on push and PR
├── Dockerfile                    # multi-stage: build web → copy into the Python image
├── docker-compose.yml            # local: postgres, qdrant, neo4j, searxng, app
├── render.yaml                   # deployed: web service, private services, Postgres, keep-alive job
├── .env.example                  # LLD-4 §5.3
├── .gitignore                    # .env, reference/geonames/*.txt, node_modules, .next, out
│
├── config/                       # keys exactly as LLD-4 §5.1, plus BD-02 additions
│   ├── searxng/settings.yml      # local SearXNG: JSON output, limiter off (BD-01)
│   ├── local.yaml                # LLD-4 §5.1, local adapters
│   └── deployed.yaml             # LLD-4 §5.1, deployed adapters
│
├── reference/                    # generic reference data only: never city facts (A-09, AT-02)
│   ├── slots.yaml                # LLD-1 §3.2
│   ├── indicators.yaml           # LLD-1 §3.3
│   ├── thresholds.yaml           # LLD-2 §4.3
│   ├── sources.yaml              # LLD-1 §3.4 (Wave 0 registry)
│   ├── publishers.yaml           # LLD-2 §14 (domain patterns, deny list)
│   ├── region_aliases.yaml       # LLD-2 §13 (generic admin-1 name aliases)
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
│   │   └── wording.py            # user-facing vocabulary (R-90)
│   ├── workflow/
│   │   ├── graph.py              # main graph and slot subgraph (LLD-2 §3)
│   │   ├── state.py              # RunState, SlotState
│   │   ├── runner.py             # run manager: start, background task, resume
│   │   ├── budget.py             # BudgetLedger (LLD-2 §12)
│   │   ├── events.py             # EventEmitter (LLD-2 §10)
│   │   ├── nodes/                # one file per node
│   │   └── rules/                # pure: crawl_gate, robots, content_usage, selection, quotes,
│   │                             #       numbers, thresholds, comparability, consistency,
│   │                             #       entity_resolution, slot_status, gap_notes, wave0_record
│   ├── query/                    # classify, retrieve, bundle, answer, postcheck (LLD-2 §15)
│   ├── report/                   # assemble, render, templates/report.{md,html}.j2 (LLD-2 §16)
│   ├── prompts/
│   │   ├── loader.py             # loads text, computes prompt_version (LLD-3 §2.5)
│   │   ├── safety.py             # <source> wrapping and escaping (LLD-3 §2.2)
│   │   └── <role>/v1.md, schema.py   # planner, extractor, checker, classifier, answerer, reporter
│   ├── ports/                    # Protocols (LLD-4 §8), one module per port with its value types; errors.py
│   └── adapters/                 # the ONLY place vendor SDKs are imported
│       ├── llm/                  # anthropic.py, openai.py, ollama.py
│       ├── embeddings/           # openai.py, sentence_transformers.py
│       ├── search/               # brave.py, searxng.py, tavily.py
│       ├── fetch/                # httpx_pinned.py
│       ├── structured/           # who_gho.py, dhs.py, world_bank.py
│       ├── vector/               # qdrant.py
│       ├── graph/                # graphiti_neo4j.py
│       ├── snapshots/            # postgres.py
│       ├── renderer/             # weasyprint.py, browser_print.py
│       ├── tracing/              # events.py, langsmith.py, otel.py
│       └── postgres/             # db.py, repos/, migrations/ (Alembic), checkpointer.py
│
├── web/                          # Next.js, static export to web/out
│   ├── app/                      # routes: / (access + start), /city/[id], /city/[id]/explore, /city/[id]/ask
│   ├── components/               # FactCard, Badge, ConfidenceReasons, CoverageGrid, EvidencePanel,
│   │                             # ProgressStream, EntityPage, EntityNeighbours, AnswerView, AdminOverlay
│   ├── lib/api.ts                # client; types generated from OpenAPI (web/lib/api-types.ts)
│   └── styles/
│
├── scripts/
│   ├── reference/                # load_geonames.py, load_yaml_reference.py
│   ├── spikes/                   # graphiti_triplets.py, who_endpoint.py, reachability.py,
│   │                             # search_links_only.py, pdf_quotes.py, run_timing.py
│   ├── purge_city.py             # LLD-1 §8
│   ├── eval_prompts.py           # LLD-3 §9
│   └── keepalive.sh              # calls /api/v1/health
│
├── tests/
│   ├── unit/                     # rules and domain
│   ├── contract/                 # one module per port (AT-35)
│   ├── acceptance/               # AT map, LLD-4 §11
│   ├── architecture/             # import-lint (AT-34), no-seeding scan (AT-02)
│   ├── smoke/                    # deployed URL (AT-17, AT-29)
│   ├── prompts/golden/           # fictional snippets and expected outputs
│   └── fixtures/                 # fictional city "Halden Bay, Norvania"; recorded provider responses
│
├── docs/
│   ├── ARCHITECTURE.md           # concise, for the panel (R-20)
│   ├── DECISIONS.md
│   ├── REHEARSAL.md
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

**Vendor packages allowed only under `app/adapters/`:** `anthropic`, `openai`, `ollama`, `sentence_transformers`, `qdrant_client`, `graphiti_core`, `neo4j`, `httpx`, `protego`, `trafilatura`, `pdfplumber`, `weasyprint`, `langsmith`, `opentelemetry`, `asyncpg`, `sqlalchemy`, `alembic`.

Expressed as import-linter `layers` and `forbidden` contracts. The architecture test fails the build on any violation.

---

## 4. Commands (poe tasks, BD-01)

Run as `uv run poe <task>`; tasks are defined in `pyproject.toml` under `[tool.poe.tasks]`.

| Command | Does |
|---|---|
| `poe up` | Start local stores and SearXNG with Docker Compose |
| `poe migrate` | Run Alembic migrations |
| `poe reference` | Download GeoNames (if missing) and load all reference data |
| `poe dev` | API with reload on :8000, plus `web` dev server on :3000 proxying `/api` |
| `poe web` | Build the static export into `web/out` |
| `poe test` | Unit, contract, architecture and acceptance tests (recorded responses) |
| `poe lint` | ruff, mypy, import-linter |
| `poe fmt` | ruff format and auto-fix |
| `poe down` | Stop local stores |
| `poe types` | Regenerate `web/lib/api-types.ts` from the OpenAPI document |
| `poe spike NAME` | Run one script in `scripts/spikes/` |
| `poe eval` | Prompt golden set against real models (costs money) |
| `poe smoke URL` | Smoke tests against a deployed URL |
| `poe purge CITY` | Remove a city from all stores |

---

## 5. Deployment files

**Dockerfile** (multi-stage): stage 1 builds `web/out` with Node; stage 2 is a slim Python 3.12 image with system libraries for WeasyPrint `[verify]`, installs with `uv`, copies `app/`, `config/`, `reference/*.yaml`, and `web/out`. Entry point runs migrations, then Uvicorn.

**render.yaml** (blueprint):

| Service | Type | Plan | Notes |
|---|---|---|---|
| `c4c-app` | Web service, Docker | Standard (2 GB) | Health check path `/api/v1/health`; auto-deploy off (R-91) |
| `c4c-neo4j` | Private service, image `neo4j:5-community` | Standard (2 GB) | Disk mounted at `/data` |
| `c4c-qdrant` | Private service, image `qdrant/qdrant` | Starter | Disk mounted at `/qdrant/storage` |
| `c4c-db` | Managed Postgres | Basic-256mb | |
| `c4c-keepalive` | Cron job, every 6 hours | Starter | Runs `scripts/keepalive.sh` |

Auto-deploy is off so nothing redeploys during rehearsals or the demo.

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
