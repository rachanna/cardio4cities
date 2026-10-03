# LLD Part 4: Interfaces

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-10-02 |
| **Status** | Baseline for build |
| **Inputs** | `REQUIREMENTS.md` v1.1 · `HLD.md` v1.0 (§11, §13, §14) · `LLD-1` to `LLD-3` |

**Scope.** HTTP API (requests, responses, errors), the event stream protocol, sessions and access control, rate limits, the Python interfaces for every port with their contract tests, the configuration schema and start-up validation, observability, and the acceptance-test map.

**For Claude Code.**
- API models live in `app/api/schemas.py` and are the single source for the OpenAPI document FastAPI generates; the front end generates its TypeScript types from that document.
- Ports are `typing.Protocol` classes in `app/ports/`. Adapters in `app/adapters/<port>/<provider>.py` are the only modules that import vendor SDKs (AT-34).
- Examples use the fictional city from LLD-3 §2.4.

---

## 1. Deployment shape change (ID-01)

The web app is still a static Next.js export, but it is **served by the API service at `/`**, with the API under `/api/v1`. HD-10 and DEC-01 placed it on a separate static site.

| Reason | Detail |
|---|---|
| Same origin | The session cookie works for the live event stream, which browsers open without custom headers. A separate origin would need third-party cookies, which browsers increasingly block |
| No CORS | Nothing to configure or get wrong on demo day |
| One fewer service | Simpler deployment and health check |

Record in `DECISIONS.md` as ID-01, superseding the hosting part of HD-10.

---

## 2. API conventions

| Topic | Rule |
|---|---|
| Base path | `/api/v1` |
| Format | JSON, UTF-8; dates `YYYY-MM-DD`; times ISO 8601 UTC |
| Auth | Session cookie from `POST /api/v1/session` (§4); every endpoint except `/session` and `/health` requires it |
| IDs | As LLD-1 §0 |
| Errors | One envelope (§6) |
| Lists | `?limit=` (default 50, max 200) and `?cursor=` (opaque) |
| Vocabulary | Responses carry both the internal value and the user-facing word (R-90), e.g. `"status": "supported", "status_word": "Confirmed"` |

### 2.1 Shared response objects

**FactCard**, used by brief, findings, answers and report:

```json
{
  "claim_id": "clm_01J9Z3K8Q2",
  "slot_id": "S04",
  "kind": "statistic",
  "statement": "In Norvania, 18.4% of adults aged 30–79 with hypertension had it under control.",
  "value_as_written": "18.4%",
  "geography": { "level": "national", "level_word": "national", "name": "Norvania" },
  "period": { "start": "2021", "end": "2021", "type": "period", "stated": true },
  "status": "supported", "status_word": "Confirmed",
  "main_badge": { "code": "not_city_level", "label": "Not city-level" },
  "other_badges": [],
  "confidence": {
    "label": "medium",
    "points": 6,
    "reasons": [
      { "component": "source_tier", "points": 2, "note": "Multilateral source" },
      { "component": "geography_fit", "points": 0, "note": "National figure for a city question" }
    ]
  },
  "source": { "source_id": "src_01J9Z3", "publisher_class": "multilateral", "title": "…", "url": "https://…" }
}
```

**SlotRow**, used by the coverage grid:

```json
{
  "slot_id": "S04", "dimension": "D2", "question": "What share of people with hypertension have it under control?",
  "headline": true, "status": "answered_wider_geo", "status_word": "Wider area only",
  "flags": [], "gap_note": "No city-level figure found. Best available is national (Norvania, 2021).",
  "best_claim_ids": ["clm_01J9Z3K8Q2"], "queries": 9, "sources": 7, "replans_used": 1
}
```

Slot status words: `answered` "Answered", `answered_wider_geo` "Wider area only", `answered_negative` "Not found", `blocked` "Blocked by source", `unreachable` "Source unreachable".

---

## 3. Endpoints

### 3.1 Session

| | |
|---|---|
| `POST /api/v1/session` | Body `{ "access_code": "…" }`. Constant-time comparison against the configured code (and admin code). 204 with a session cookie; 401 otherwise. Five failures per IP per 10 minutes → 429 |
| `DELETE /api/v1/session` | Clears the cookie |

Cookie: signed token (HMAC with `SESSION_SECRET`), `HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=43200`. Claims: `role` (`viewer` or `admin`), `iat`, `exp`.

### 3.2 Cities and runs

**`POST /api/v1/cities/resolve`**

```json
// request
{ "query": "Halden Bay" }
// 200
{
  "exact": false,
  "candidates": [
    { "gazetteer_id": "9990001", "name": "Halden Bay", "admin1_name": "Coast Province",
      "country_name": "Norvania", "country_iso2": "NV", "population": 412000 },
    { "gazetteer_id": "9990057", "name": "Halden", "admin1_name": "Upland", "country_name": "Norvania",
      "country_iso2": "NV", "population": 38000 }
  ]
}
```

Trigram search on name and alternate names, ranked by similarity then population, top 5. `exact = true` only when one candidate matches exactly and no other candidate is within similarity 0.1. The UI always shows the chosen identity before starting (HD-02, AT-24).

**`POST /api/v1/runs`**: starts a fresh run (R-83)

```json
// request
{ "gazetteer_id": "9990001" }
// 202
{ "run_id": "run_01J9Z4", "city_id": "city_01J9Z4", "status": "queued",
  "events_url": "/api/v1/runs/run_01J9Z4/events" }
```

| Error | When |
|---|---|
| 409 `run_in_progress` | Another run is running (one at a time, CON-10) |
| 429 `daily_run_limit` | Daily run limit reached |
| 404 `place_not_found` | Unknown `gazetteer_id` |

The `city` row is created on first research of a place and reused afterwards; every call creates a new `run`.

**`GET /api/v1/runs/{run_id}`**

```json
{ "run_id": "run_01J9Z4", "city_id": "city_01J9Z4", "status": "completed",
  "started_at": "…", "finished_at": "…", "summary": { /* RunSummary, LLD-1 §2.7 */ },
  "versions": { "planner": "claude-sonnet-5-5 / planner@v1+3fa2c19d", "…": "…" } }
```

**`GET /api/v1/cities`**: "Open existing"

```json
{ "items": [ { "city_id": "city_01J9Z4", "name": "Halden Bay", "country_name": "Norvania",
  "latest_run_id": "run_01J9Z4", "latest_run_at": "2026-10-03T09:12:00Z",
  "latest_run_status": "completed" } ], "next_cursor": null }
```

### 3.3 Reading a city

| Endpoint | Returns |
|---|---|
| `GET /api/v1/cities/{city_id}/brief` | `city` (CityIdentity), `run` (id, date, status), `summary` (per dimension: up to 3 FactCards with confidence High or Medium, HD-08), `coverage` (16 SlotRows), `handle_with_care` (FactCards plus a `reason`), `counts` (run summary) |
| `GET /api/v1/cities/{city_id}/findings` | FactCards filtered by `dimension`, `slot`, `status`, `badge`; plus `contested` pairs |
| `GET /api/v1/cities/{city_id}/entities` | Entities by type with edge counts |
| `GET /api/v1/cities/{city_id}/entities/{entity_id}` | The entity and its one-hop edges: `relation`, `direction`, `other_entity`, `valid_from`, `valid_to`, `status` (`current`, `ended`, `contested`), `claim_ids` |
| `GET /api/v1/facts/{claim_id}/evidence` | Everything from `v_fact_evidence` plus `passage` (the located quote with up to 600 characters of context), `highlight` offsets, `verdict` (label, rationale, model, fallback flag), `snapshot` (sha256, size, URL), `consistency` (outcome, compared claims) |
| `GET /api/v1/snapshots/{source_id}` | The raw stored bytes with their original content type, header `X-Snapshot-SHA256`, and `Content-Disposition: inline` |

Only facts in `v_city_facts` (LLD-1 §4.6) are returned as FactCards. A request for the evidence of a refuted or dropped claim returns it with `"status_word": "Reported, not confirmed"`, so the panel can inspect rejected claims during DS-3.

### 3.4 Questions and reports

**`POST /api/v1/cities/{city_id}/ask`**

```json
// request
{ "question": "Who runs public health in Halden Bay now?", "options": { "graph": "on" },
  "conversation_id": "conv_01J9Z6" }              // optional (CHG-01); the server creates one when absent
// 200
{
  "answer_id": "ans_01J9Z6",
  "question_type": "relationship",
  "sentences": [
    { "text": "Public health in Halden Bay is run by the Halden Bay Metropolitan Health Office.",
      "kind": "fact", "refs": ["clm_01J9Z5A1"],
      "main_badge": null, "status_word": "Confirmed" },
    { "text": "No confirmed leader of that office was found. Searched 6 queries in 2 languages and checked 5 sources.",
      "kind": "abstain", "refs": [], "slot_id": "S12" }
  ],
  "graph_used": true,
  "run_id": "run_01J9Z4",
  "conversation_id": "conv_01J9Z6", "turn": 1,   // CHG-01 (LLD-5 §3.2)
  "trace": { "...": "admins only (LLD-5 §10)" }
}
```

`options.graph = "off"` requires the admin role (R-88); otherwise 403. Responses for `out_of_scope` contain one sentence of kind `abstain` with no slot.

**`GET /api/v1/cities/{city_id}/report?format=md|html|pdf`**: generates on first request per run and format, then serves the stored copy. `Content-Disposition: attachment; filename="<city>-research-<date>.<ext>"`.

### 3.5 Operations and demonstration

| Endpoint | Role | Returns |
|---|---|---|
| `GET /api/v1/health` | none | §7 |
| `GET /api/v1/workflow/diagram` | viewer | Mermaid text generated from the compiled graphs (`draw_mermaid`), main graph and slot subgraph, for DS-2 (AT-03) |
| `GET /api/v1/admin/planted-cases` | admin | The planted trust cases (HLD §9.5) with their last results |
| `POST /api/v1/admin/planted-cases/{case_id}/run` | admin | Runs one planted case against the live components and returns the outcome with the claim, verdict and consequence |
| `GET /api/v1/admin/answers/{answer_id}/trace` | admin | The stored retrieval trace of one answer (CHG-01, LLD-5 §10) |
| `GET /api/v1/admin/runs/{run_id}/trace` | admin | Link to the tracing provider for the run, when configured |

---

## 4. Event stream protocol (R-80, AT-30)

`GET /api/v1/runs/{run_id}/events` returns `text/event-stream`.

```text
id: 17
event: crawl_decision
data: {"url":"https://…","domain":"…","outcome":"blocked_robots","reason":"Disallow: /reports/ for *"}

: heartbeat

id: 18
event: source_fetched
data: {"source_id":"src_01J9Z4C2","url":"https://…","publisher_class":"government","kind":"web_pdf"}
```

| Rule | Detail |
|---|---|
| `id` | The event's `seq` (LLD-1 §4.2) |
| Resume | The browser sends `Last-Event-ID` on reconnect; the server first replays stored events with `seq` greater than it, in order, then follows live events. No duplicates, no gaps |
| Live following | The server polls `run_event` every 500 ms `[tunable]` after replay, so live delivery works even if the run executes in another process later |
| Heartbeat | A comment line every 15 s to keep proxies from closing the connection |
| End | After `run_finished`, the server sends it and closes. A client that connects after the run ended receives the full replay, then the close |
| Retry hint | `retry: 2000` sent once at the start |

The UI builds progress, the coverage grid and Wave 0 findings from events alone; it fetches `/brief` once `run_finished` arrives.

---

## 5. Configuration

### 5.1 Files and secrets

`config/<env>.yaml` (`local`, `local-quality`, `deployed`; BD-05) selects adapters and parameters. Secrets come only from environment variables; YAML refers to them by name. Each model binding (role, `escalate_to`, `fallback`) may set `effort` or `temperature`, never both, and only what its model accepts; providers may name a `base_url_env`. The block below is the original baseline; `config/*.yaml` hold the current bindings.

```yaml
app:
  public_base_url: https://<host>
  user_agent: "CARDIO4CitiesResearchBot/0.1 (+https://github.com/<repo>)"
access:
  access_code_env: ACCESS_CODE
  admin_code_env: ADMIN_CODE
  session_secret_env: SESSION_SECRET
llm:
  roles:
    planner:    { provider: anthropic, model: claude-sonnet-5-5, family: anthropic }
    extractor:  { provider: anthropic, model: claude-haiku-4-5-20251001, family: anthropic,
                  escalate_to: { provider: anthropic, model: claude-sonnet-5-5 } }
    checker:    { provider: openai, model: "<confirm day 1>", family: openai,
                  fallback: { provider: anthropic, model: claude-opus-5-5, family: anthropic } }
    classifier: { provider: anthropic, model: claude-haiku-4-5-20251001, family: anthropic }
    answerer:   { provider: anthropic, model: claude-sonnet-5-5, family: anthropic }
    reporter:   { provider: anthropic, model: claude-sonnet-5-5, family: anthropic }
  providers:
    anthropic: { api_key_env: ANTHROPIC_API_KEY }
    openai:    { api_key_env: OPENAI_API_KEY }
    ollama:    { base_url: http://ollama:11434 }
  concurrency: 4
  allow_same_family_checker: false   # BD-02; see §5.2
embeddings: { provider: openai, model: "<confirm day 1>", dimension: 0, key: openai_small_v1 }
search:     { provider: brave, mode: links_only, api_key_env: BRAVE_API_KEY, rate_per_s: 1 }
            # searxng (local): { provider: searxng, mode: links_only, base_url: http://localhost:8888, rate_per_s: 1 } (BD-02)
relational: { dsn_env: DATABASE_URL }
vector:     { provider: qdrant, url_env: QDRANT_URL, api_key_env: QDRANT_API_KEY }
graph:      { provider: graphiti_neo4j, uri_env: NEO4J_URI, user_env: NEO4J_USER, password_env: NEO4J_PASSWORD }
snapshots:  { provider: postgres, max_bytes: 10485760 }
renderer:   { provider: weasyprint }
tracing:    { providers: [events, langsmith], langsmith_api_key_env: LANGSMITH_API_KEY }
budget:     { wall_clock_s: 300, searches: 48, fetches: 60, tokens: 0, cost_micro_usd: 0, wind_down_at: 0.85 }
limits:     { runs_per_day: 20, ask_per_min: 20, resolve_per_min: 30 }
fetch:      { concurrency: 6, min_interval_s: 1, max_bytes: 10485760, connect_timeout_s: 5, read_timeout_s: 20,
              allowed_ports: [80, 443], robots_timeout_s: 15 }   # BD-07
chunk:      { prose_tokens: 400, overlap_tokens: 60, table_max_tokens: 1200 }   # BD-07
verify:     { max_claims_per_slot: 5, label_margin_chars: 200 }   # BD-10
geography:  { nearby_km: 75 }   # BD-10
eval:       { checker_agreement_min: 0.9 }   # LLD-3 §9
stream:     { poll_interval_s: 0.5, heartbeat_s: 15 }   # BD-09
select:     { max_new_urls_per_slot_round: 4 }
replan:     { max_rounds: 2, max_rounds_wider_geo: 1 }
extract:    { window_tokens: 12000, overlap_tokens: 500 }
quote:      { min_words: 6, max_words: 60 }   # BD-06
consistency:{ agree_pp: 0.5, agree_rel: 0.02 }
entity:     { merge_threshold: 0.92, candidate_threshold: 0.85 }
badge:      { stale_years: 5, stale_years_people: 2, small_sample: 300 }
confidence: { recent_years: 5 }
analytics:  { enabled: false }
retrieval:                                   # CHG-01 (LLD-5 §14)
  rrf_k: 60
  r2_top: 20
  r2_trigram_min: 0.4
  r3_top: 20
  r3_mentions_top: 5
  max_facts: 8
  max_mentions: 4
  max_per_slot: 2
  mentions_only_if_facts_below: 3
```

`0` for `tokens`, `cost_micro_usd` and `dimension` means "not yet set". Start-up refuses `0` in `deployed`.

### 5.2 Start-up validation (R-82, AT-36)

The application refuses to start, with a message naming the problem, when:

| Check | Rule |
|---|---|
| Checker independence | `checker.family == extractor.family` and no `fallback` path is in use: refuse. A same-family primary checker is allowed only with `allow_same_family_checker: true`, which is then shown on every verdict and in `/health` |
| Embedding model | Provider's reported dimension ≠ `embeddings.dimension`; or the Qdrant collection `source_chunks__{key}` exists with a different vector size |
| Secrets | Any `*_env` referenced by an enabled adapter is missing |
| Placeholders | Any value `"<confirm day 1>"` or a `0` budget in `deployed` |
| Reference data | `ref_slot` does not hold exactly S01–S16; `ref_source` contains placeholder indicator codes |
| Access | `ACCESS_CODE` shorter than 12 characters; `ADMIN_CODE` equal to `ACCESS_CODE` |
| Multilingual embeddings | The local Sentence Transformers model must be on the configured multilingual list (R-100, CHG-01) |

### 5.3 `.env.example`

```text
ACCESS_CODE=            # shared with the panel
ADMIN_CODE=             # for the graph switch and planted cases
SESSION_SECRET=         # 32+ random bytes, base64
DATABASE_URL=           # postgresql://…
QDRANT_URL=
QDRANT_API_KEY=         # empty for local
NEO4J_URI=
NEO4J_USER=
NEO4J_PASSWORD=
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
BRAVE_API_KEY=          # empty locally when search uses SearXNG
LANGSMITH_API_KEY=      # optional
APP_ENV=local           # local | deployed
```

---

## 6. Errors

```json
{ "error": { "code": "run_in_progress", "message": "A research run is already in progress. Try again when it finishes.", "details": { "run_id": "run_01J9Z4" } } }
```

| HTTP | Code | When |
|---|---|---|
| 400 | `invalid_request` | Schema validation failed |
| 401 | `unauthenticated` | No or expired session; wrong access code |
| 403 | `forbidden` | Admin-only option or endpoint |
| 404 | `not_found`, `place_not_found` | Unknown ID |
| 409 | `run_in_progress` | One run at a time |
| 409 | `no_research_yet` | Ask, brief or report for a city with no completed run |
| 413 | `question_too_long` | Over 500 characters |
| 429 | `rate_limited`, `daily_run_limit` | Limits in §4 of config |
| 503 | `dependency_unavailable` | A store is down; `details.component` names it |
| 500 | `internal_error` | Anything else; logged with a request ID |

Messages are written for the City Lead: they say what happened and what to do, without apology or internal terms.

---

## 7. Health (R-77, AT-29)

`GET /api/v1/health` (no auth; no secrets or URLs in the body):

```json
{
  "status": "ok",
  "checked_at": "2026-10-03T08:00:00Z",
  "components": {
    "postgres":   { "status": "ok", "latency_ms": 4 },
    "qdrant":     { "status": "ok", "latency_ms": 9, "collection": "source_chunks__openai_small_v1" },
    "neo4j":      { "status": "ok", "latency_ms": 12 },
    "llm_anthropic": { "status": "ok" },
    "llm_openai": { "status": "ok" },
    "embeddings": { "status": "ok" },
    "search":     { "status": "ok" },
    "reference_data": { "status": "ok", "slots": 16 }
  },
  "checker_independence": "different_family",
  "versions": { "app": "1.0.0", "prompts": { "planner": "planner@v1+3fa2c19d" } }
}
```

| Rule | Detail |
|---|---|
| Stores | A trivial query each (`SELECT 1`, collection info, `RETURN 1`) |
| Providers | A cached lightweight check (model list or a one-token call) at most every 10 minutes, so health checks do not burn budget |
| Overall status | `ok` only if every component is `ok`; otherwise `degraded` with HTTP 503 |
| Keep-alive | A scheduled job calls `/health` every 6 hours during the evaluation window `[tunable]`, which also keeps any free-tier store awake |

---

## 8. Ports

All ports are async. Each has one contract-test module in `tests/contract/test_<port>.py` that every adapter must pass (AT-35).

```python
class LLMPort(Protocol):
    async def complete(self, role: str, system: str, user: str,
                       schema: type[BaseModel], params: LLMParams) -> LLMResult: ...
    # LLMResult: parsed (BaseModel), raw_text, model_id, family, tokens_in, tokens_out, cost_micro_usd

class EmbeddingsPort(Protocol):
    @property
    def dimension(self) -> int: ...
    @property
    def key(self) -> str: ...
    async def embed(self, texts: list[str]) -> list[list[float]]: ...

class SearchPort(Protocol):
    async def search(self, query: str, lang: str, limit: int = 10) -> list[SearchHit]: ...
    # SearchHit: url, title, snippet, rank. Adapters MUST disable provider content retrieval.

class FetchPort(Protocol):                     # reshaped by BD-07
    async def resolve(self, host: str) -> list[str]: ...
    async def fetch(self, url: str, pinned_ip: str, limits: FetchLimits) -> FetchResult: ...
    # One request, no redirects followed: the collector re-gates every hop (AT-23).
    # robots.txt is fetched by the collector through the same port.

class RobotsParser(Protocol):                  # BD-07: wraps Protego; Content-Usage parsed by our code
    def parse(self, text: str) -> RobotsRules: ...

class ParserPort(Protocol):                    # BD-07: trafilatura (HTML), pdfplumber (PDF)
    def parse_html(self, content: bytes, url: str) -> ParsedDocument: ...
    def parse_pdf(self, content: bytes, table_keywords: list[str]) -> ParsedDocument: ...

class StructuredDataPort(Protocol):     # reshaped by BD-13: pure; I/O through Collector.fetch_api
    provider: str
    def request_urls(self, code: str, country_iso3: str, params: Mapping[str, Any]) -> list[str]: ...
    def parse(self, code: str, raw: bytes) -> list[StructuredRecord]: ...
    # StructuredRecord: indicator_code, area_code, year, sex, age_group, value_as_written, display

class VectorPort(Protocol):
    async def ensure_collection(self, name: str, dimension: int) -> None: ...
    async def collection_dimension(self, name: str) -> int | None: ...   # §5.2 check (BD-02)
    async def upsert(self, name: str, points: list[VectorPoint]) -> None: ...
    async def search(self, name: str, vector: list[float], filters: dict, limit: int) -> list[VectorHit]: ...
    async def delete_by_filter(self, name: str, filters: dict) -> None: ...

class GraphPort(Protocol):
    async def upsert_entity(self, entity: GraphEntity) -> None: ...
    async def add_triplet(self, subject: GraphEntity, edge: GraphEdge, obj: GraphEntity) -> str: ...
    async def invalidate_edge(self, edge_uuid: str, invalid_at: date) -> None: ...
    async def search_edges(self, group_id: str, relation_types: list[str],
                           as_of: date | None = None, include_ended: bool = False,
                           query: str | None = None, limit: int = 20) -> list[GraphEdgeHit]: ...
    async def neighbours(self, group_id: str, entity_uuid: str) -> list[GraphEdgeHit]: ...
    async def export_subgraph(self, group_id: str) -> GraphExport: ...
    async def delete_group(self, group_id: str) -> None: ...

class SnapshotPort(Protocol):
    async def put(self, source_id: str, content: bytes, content_type: str) -> SnapshotRef: ...
    async def get(self, source_id: str) -> tuple[bytes, str]: ...

class RendererPort(Protocol):
    async def to_pdf(self, html: str) -> bytes: ...

class TracingPort(Protocol):
    def span(self, name: str, **attrs) -> AbstractAsyncContextManager: ...
    def event(self, name: str, **attrs) -> None: ...
```

Relational access uses repository classes per aggregate (`RunRepo`, `ClaimRepo`, `SourceRepo`, `EntityRepo`, `SlotRepo`, `AnswerRepo`, `ReportRepo`, `EventRepo`) over async SQLAlchemy Core. Postgres is a fixed choice (CON-04), so the repositories are the port and SQL lives only in `app/adapters/postgres/`.

### 8.1 Adapters for the PoC

| Port | Deployed default | Local or alternative |
|---|---|---|
| LLM | `anthropic`, `openai` | `ollama` |
| Embeddings | `openai` | `sentence_transformers` |
| Search | `brave` | `searxng`; `tavily` (content retrieval forced off) |
| Fetch | `httpx` with pinned-IP transport | same |
| Structured data | `who_gho`, `world_bank` (DHS dropped, BD-13) | same |
| Vector | `qdrant` | same |
| Graph | `graphiti_neo4j` | same |
| Snapshots | `postgres` | `s3` (COULD) |
| Renderer | `weasyprint` `[verify on host]` | `browser_print` (returns HTML with print styles) |
| Tracing | `events` + `langsmith` | `events` + `otel` |

### 8.2 Contract-test highlights

| Port | Must prove |
|---|---|
| LLM | Returns a parsed object of the requested schema; reports model ID, family and token counts; a validation failure surfaces as a typed error |
| Search | Hits contain URL, title and snippet only; the request sent to the provider has content retrieval disabled (AT-33) |
| Fetch | Refuses a URL whose host resolves to a private address; honours size limit; reports redirect chains |
| Vector | Upsert is idempotent by point ID; filter by `city_id` never returns another city's points |
| Graph | Entity UUIDs are preserved; an invalidated edge is still returned with `include_ended=True` |
| Structured data | Raw bytes returned unchanged, so code verification can re-read them |

---

## 9. Observability

| Signal | Content |
|---|---|
| Run events | LLD-2 §10; always on; the primary record of a run |
| Tracing spans | `run`, `node:<name>`, `slot:<slot_id>`, `llm:<role>`, `fetch`, `search`, `graph:write`; attributes include `run_id`, `slot_id`, model ID, tokens, outcome |
| Logs | JSON lines with `request_id` and `run_id`; never the access codes, cookies or API keys; page content never logged |
| Run summary | LLD-1 §2.7; shown in the UI and the report |

---

## 10. Security checklist

- [ ] Access and admin codes compared in constant time; failed attempts rate-limited
- [ ] Session cookie `HttpOnly`, `Secure`, `SameSite=Strict`, signed, 12-hour expiry
- [ ] Stores reachable only on the private network; no public ports
- [ ] Fetch adapter pins resolved IPs and refuses private, loopback, link-local and metadata ranges (AT-23)
- [ ] All fetched text escaped inside `<source>` tags (LLD-3 §2.2)
- [ ] No vendor SDK outside adapters (AT-34)
- [ ] Secrets only from environment; `.env` git-ignored; `.env.example` complete
- [ ] `/health` reveals no hostnames, URLs or keys
- [ ] Snapshots served with their original content type and `X-Content-Type-Options: nosniff`; HTML snapshots served with a restrictive `Content-Security-Policy: sandbox` so stored pages cannot run scripts in the app's origin

---

## 11. Acceptance-test map

| AT | Test location | Type |
|---|---|---|
| AT-01 | `tests/acceptance/test_live_run.py::test_unseen_city_fetches_after_request` | Automated (recorded network) |
| AT-02 | `tests/acceptance/test_no_seeding.py` | Automated (scans prompts, config, reference, fixtures for gazetteer place names and per-city URL lists) |
| AT-03 | `tests/acceptance/test_workflow_graph.py` | Automated |
| AT-04, AT-05, AT-06, AT-23, AT-33 | `tests/acceptance/test_crawl_gate.py` | Automated (local test server) |
| AT-07, AT-08 | `tests/acceptance/test_checker.py` | Automated |
| AT-09 | `tests/unit/test_quote_match.py` + acceptance | Automated |
| AT-10, AT-11 | `tests/acceptance/test_graph_used.py` | Automated |
| AT-12, AT-27 | `tests/acceptance/test_evidence.py` | Automated |
| AT-13, AT-14, AT-21, AT-31 | `tests/acceptance/test_scope_and_badges.py` | Automated |
| AT-15, AT-28 | `tests/acceptance/test_answers.py` | Automated |
| AT-16, AT-32 | `tests/acceptance/test_sparse_city.py` | Automated (fixture of a sparse fictional city) |
| AT-17, AT-29 | `tests/smoke/test_deployed.py` | Automated against the deployed URL |
| AT-18 | `tests/acceptance/test_report.py` | Automated |
| AT-19 | `tests/acceptance/test_budget.py` | Automated |
| AT-20 | `tests/acceptance/test_conflicts.py` | Automated |
| AT-22 | `tests/acceptance/test_injection.py` | Automated |
| AT-24 | `tests/acceptance/test_resolve.py` | Automated |
| AT-25, AT-37 | `tests/acceptance/test_reuse_and_fresh.py` | Automated |
| AT-26 | `tests/unit/test_entity_resolution.py` | Automated |
| AT-30 | `tests/acceptance/test_event_replay.py` | Automated |
| AT-34 | `tests/architecture/test_import_lint.py` | Automated |
| AT-35 | `tests/contract/` | Automated |
| AT-36 | `tests/acceptance/test_config_validation.py` | Automated |
| AT-38 | `tests/acceptance/test_run_summary.py` | Automated |
| AT-39 to AT-46 | `tests/acceptance/test_retrieval.py` | Automated (CHG-01) |
| AT-47 | `tests/acceptance/test_retrieval_eval.py` | Automated (CHG-01) |
| R-14 exploration, DS-1 to DS-7 | `docs/REHEARSAL.md` checklist | Demo rehearsal |

Tests that would call paid providers use recorded responses in CI; `scripts/eval_prompts.py` and the deployed smoke test are the only live runs.

---

## 12. Screens to endpoints

| Screen | Calls |
|---|---|
| Access | `POST /session` |
| Start | `POST /cities/resolve`, `POST /runs`, `GET /runs/{id}/events`, `GET /cities` |
| City brief | `GET /cities/{id}/brief`, `GET /cities/{id}/report` |
| Explore | `GET /cities/{id}/findings`, `GET /cities/{id}/entities`, `GET /cities/{id}/entities/{eid}` |
| Ask | `POST /cities/{id}/ask` |
| Evidence panel | `GET /facts/{claim_id}/evidence`, `GET /snapshots/{source_id}` |
| Admin overlay (demo) | `GET /workflow/diagram`, `GET /admin/planted-cases`, `POST /admin/planted-cases/{id}/run`, `ask` with `graph: "off"` |

---

## 13. Decisions made in this part

| ID | Decision | Alternative | Reason |
|---|---|---|---|
| ID-01 | API serves the static web app on the same origin | Separate static site | Session cookie works for the event stream; no CORS; one fewer service. Supersedes the hosting part of HD-10 |
| ID-02 | Cookie session from an access code | Code in a header on every request | Browsers' event streams cannot send custom headers |
| ID-03 | Event stream replays from Postgres, then polls | Stream from memory only | Correct after reconnects and process restarts (R-80) |
| ID-04 | Postgres repositories are the relational port | A generic relational interface | Postgres is fixed by constraint; a generic layer adds no value |
| ID-05 | Health checks of paid providers cached for 10 minutes | Live check each call | Keep-alive must not spend budget |
| ID-06 | Stored HTML snapshots served sandboxed | Served as-is | A stored page must not run scripts in the app's origin |

## 14. Open items

| Item | Resolve by |
|---|---|
| Checker and embedding model IDs, embedding dimension | Day 1 |
| WeasyPrint on the host | Day 1 |
| Brave request parameters that guarantee links only | Day 1 (contract test) |
| Keep-alive scheduler (host cron job or external pinger) | Deployment day |
