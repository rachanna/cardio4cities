# LLD Part 1: Data Model

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-10-02 |
| **Status** | Baseline for build |
| **Inputs** | `REQUIREMENTS.md` v1.1 · `HLD.md` v1.0 (§6 data architecture) · `BRAINSTORM.md` v1.0 |
| **Read with** | `LLD-2-workflow.md` (algorithms that read and write this data) · `LLD-4-interfaces.md` (API and ports) |

**Scope.** Every persistent and in-flight data structure: domain types, controlled vocabularies, reference data, the Postgres schema, the Qdrant collection, the Graphiti ontology and write contract, provenance queries, and data lifecycle.

**For Claude Code.**
- Domain types live in `app/domain/` as Pydantic v2 models and `StrEnum`s, and import no vendor SDK.
- The Postgres schema is created by migrations in `app/adapters/postgres/migrations/` (Alembic), never by ORM auto-create.
- Names here are binding: tables, columns, enum values and Qdrant payload keys are used as written.
- Items marked `[spike]` are confirmed by a day-1 spike; build the primary design and keep the fallback path open.
- Items marked `[tunable]` are configuration values with the default shown.

---

## 0. Conventions

| Topic | Rule |
|---|---|
| IDs | Prefixed ULIDs generated in the app: `city_`, `run_`, `src_`, `clm_`, `ent_`, `evt_`, `ans_`, `cp_`, `cd_`, `sq_`. Sortable by time, readable in logs and citations (decision LD-01) |
| Graph IDs | Entity and edge IDs in Graphiti are UUIDs derived deterministically from our IDs (`uuid5(NAMESPACE, ent_…)`), so we control identity (HD-06) |
| Time | `timestamptz`, always UTC. Dates from sources stored as `date` plus a precision field |
| Text | UTF-8; quotes stored exactly as found in the parsed source, never normalised in storage |
| Money | Model cost stored in micro-US-dollars (`bigint`) to avoid float drift |
| Nulls | A label the source does not state is `NULL`, never a guessed value (R-89) |
| Enums | Stored as `text` with a `CHECK` constraint listing allowed values, so adding a value is a migration, not a type change |
| Database | PostgreSQL 16 |

---

## 1. Controlled vocabularies

All in `app/domain/vocab.py` as `StrEnum`s. The database `CHECK` constraints use the same values.

### 1.1 Claims and statistics

| Enum | Values | Notes |
|---|---|---|
| `ClaimKind` | `statistic`, `relation`, `statement` | Statistic has a numeric value; relation becomes a graph edge; statement is any other fact (a policy exists, a programme is running) |
| `GeographyLevel` | `city_wide`, `sub_city_area`, `sub_city_population`, `metro_region`, `district`, `state_province`, `national`, `global` | What the figure actually describes. Ordered from finest to broadest |
| `Representativeness` | `representative_sample`, `census`, `non_representative`, `modelled`, `not_applicable` | `not_applicable` for relations and statements |
| `MeasureType` | `measured_prevalence`, `self_reported_prevalence`, `screening_positivity`, `cascade_awareness`, `cascade_treatment`, `cascade_control`, `share_of_subgroup`, `incidence`, `mortality_rate`, `programme_output`, `modelled_estimate`, `target`, `budget`, `population_count`, `qualitative` | Screening positivity and programme output are never prevalence (T-04) |
| `Method` | `measured`, `self_reported`, `modelled`, `administrative`, `not_stated` | |
| `PeriodType` | `point_in_time`, `period`, `cumulative`, `publication_date_proxy` | `publication_date_proxy` when the source states no reference period; always flagged (§2.3) |
| `DatePrecision` | `day`, `month`, `year` | |
| `Sex` | `all`, `female`, `male`, `not_stated` | |
| `ClaimStatus` | `extracted`, `dropped`, `supported`, `refuted`, `insufficient`, `contested`, `superseded` | Lifecycle in LLD-2 §5 (R-47) |
| `ClaimFlag` | `period_not_stated`, `denominator_not_stated`, `small_sample`, `non_representative`, `republished`, `translated`, `value_unparsed`, `setting_not_stated`, `governing_body_uncertain` | Stored flags. Badges are computed at read time (§1.4) |

### 1.2 Sources, crawling, verification

| Enum | Values |
|---|---|
| `SourceKind` | `web_html`, `web_pdf`, `structured_api` |
| `PublisherClass` | `government`, `multilateral`, `academic`, `ngo`, `news`, `other` (this order is also the source tier, best first) |
| `CrawlOutcome` | `allowed`, `blocked_robots`, `blocked_content_usage`, `blocked_login_or_paywall`, `blocked_private_address`, `unreachable_network`, `unreachable_server_error`, `rate_limited` |
| `ParseOutcome` | `parsed`, `unreadable`, `too_large`, `unsupported_type` |
| `VerdictLabel` | `supported`, `refuted`, `insufficient` |
| `ConsistencyOutcome` | `agrees`, `novel`, `conflicts`, `not_comparable` |

### 1.3 Runs, slots, events

| Enum | Values |
|---|---|
| `RunStatus` | `queued`, `running`, `completed`, `stopped_by_budget`, `failed` |
| `SlotStatus` | `answered`, `answered_wider_geo`, `answered_negative`, `blocked`, `unreachable` |
| `SlotFlag` | `conflicting`, `stale` |
| `EventType` | `run_started`, `identity_confirmed`, `wave0_finding`, `slot_planned`, `search_done`, `crawl_decision`, `source_fetched`, `source_unreadable`, `claim_extracted`, `claim_dropped`, `claim_verdict`, `conflict_found`, `fact_written`, `slot_status`, `budget_warning`, `run_finished` |

### 1.4 Presentation (computed, never stored)

| Enum | Values | Rule |
|---|---|---|
| `Badge` | `not_city_level` > `sources_disagree` > `outdated` > `limited_sample` | One main badge per fact by this order (R-78); algorithm in LLD-2 §8 |
| `ConfidenceLabel` | `high`, `medium`, `low` | Deterministic function in LLD-2 §7 |
| `StatementKind` | `confirmed`, `reported_not_confirmed`, `analysis`, `not_found` | Maps to the user vocabulary (R-90) |

---

## 2. Domain types

Pydantic v2, `app/domain/models.py`. Shown in abbreviated form; field names, types and validators are binding.

### 2.1 City identity

```python
class CityIdentity(BaseModel):
    city_id: str                     # city_…
    gazetteer_id: str                # e.g. GeoNames id as text
    name: str                        # canonical display name
    ascii_name: str
    country_iso2: str                # 'GH'
    country_iso3: str                # 'GHA'
    country_name: str
    admin1_code: str | None          # first-level region code
    admin1_name: str | None
    admin2_name: str | None
    population: int | None           # from gazetteer, used only for sanity checks (T-10)
    lat: float
    lon: float
    languages: list[str]             # ISO 639-1, from country reference; first is primary
```

### 2.2 Slot definition (reference data)

```python
class SlotDef(BaseModel):
    slot_id: str                     # 'S01'…'S16'
    dimension: str                   # 'D1'…'D6'
    question: str                    # plain-language question shown in UI
    short_label: str                 # "No confirmed {short_label} for {city}" (LLD-2 §15.2; BD-03)
    answer_kind: Literal['statistic', 'relation', 'statement', 'mixed']
    indicator_codes: list[str]       # for statistic slots; see §3.3
    relation_types: list[str]        # for relation slots; see §6.2
    headline: bool                   # True only for S04
    accepted_levels: list[GeographyLevel]   # levels that count as 'answered' rather than 'answered_wider_geo'
```

### 2.3 Claim and labels

```python
class Labels(BaseModel):
    # Required for display (R-89). Missing → claim kept but never shown as a figure.
    geography_level: GeographyLevel
    geography_name: str              # as the source names it: 'Ashanti Region', 'Ghana'
    measure_type: MeasureType
    reference_start: date | None
    reference_end: date | None
    reference_precision: DatePrecision | None
    period_type: PeriodType          # publication_date_proxy when no period stated
    # Optional: NULL when the source does not state it
    population_age_min: int | None
    population_age_max: int | None
    population_sex: Sex = Sex.not_stated
    population_group: str | None     # 'adults', 'university staff', 'clinic patients'
    setting: str | None              # 'community', 'hospital', 'workplace'; NULL → flag setting_not_stated
    sample_size: int | None
    case_definition: str | None      # as written: 'SBP>=140 and/or DBP>=90, or on medication'
    threshold_code: str | None       # normalised by code: 'bp_140_90', 'bp_130_80' (§3.3)
    method: Method = Method.not_stated
    representativeness: Representativeness
    denominator_text: str | None     # 'adults with hypertension'
    denominator_stated: bool

class Claim(BaseModel):
    claim_id: str                    # clm_…
    run_id: str
    city_id: str
    slot_id: str
    source_id: str
    kind: ClaimKind
    statement: str                   # one sentence in English
    quote: str                       # verbatim from the parsed source, original language
    quote_lang: str                  # ISO 639-1
    quote_translation: str | None    # English, when quote_lang != 'en'
    span_start: int                  # character offsets in the parsed text, located by code
    span_end: int
    labels: Labels
    flags: set[ClaimFlag]
    status: ClaimStatus
    extractor_model: str
    prompt_version: str
```

**Reference period rule.** When the source states no reference period, the extractor leaves `reference_start` and `reference_end` empty. Code then sets `period_type = publication_date_proxy`, copies the source's publication date into `reference_end` with its precision, and adds `period_not_stated`. The figure can be shown, but its evidence panel says the period was not stated.

### 2.4 Statistic

A claim with `kind = statistic` has exactly one `Statistic`.

```python
class Statistic(BaseModel):
    claim_id: str
    indicator_code: str              # §3.3; 'OTHER' allowed, never compared
    value_as_written: str            # '21.7%', '1 in 3', '9,5 %'
    value_num: Decimal | None        # parsed by CODE from value_as_written, never by the model
    unit: str | None                 # 'percent', 'per_100k', 'count'
    lower: Decimal | None            # confidence interval or range, if stated
    upper: Decimal | None
```

`value_num` parsing rules live in LLD-2 §4. If parsing fails, `value_num` is `NULL`, the flag `value_unparsed` is set, and the figure is shown only as written and never compared.

### 2.5 Relation

A claim with `kind = relation` has exactly one `Relation`, which becomes one graph edge once supported.

```python
class Relation(BaseModel):
    claim_id: str
    subject_entity_id: str           # ent_…, resolved by code (LLD-2 §6)
    relation_type: RelationType      # §6.2
    object_entity_id: str
    valid_from: date | None
    valid_to: date | None
    valid_from_is_proxy: bool        # True when publication date stands in
```

### 2.6 Verdict, consistency, source, crawl decision

```python
class Verdict(BaseModel):
    claim_id: str
    label: VerdictLabel
    rationale: str                   # ≤ 400 chars
    scope_verified: bool             # checker agrees geography and population match the passage
    period_verified: bool
    verifier_model: str
    verifier_family: str             # 'openai', 'anthropic', … used by R-82 validation
    fallback_used: bool              # True when same-family fallback judged it
    prompt_version: str

class ConsistencyResult(BaseModel):
    claim_id: str
    outcome: ConsistencyOutcome
    compared_with: list[str]         # claim_ids
    reason: str                      # template text from code

class Source(BaseModel):
    source_id: str                   # src_…
    run_id: str
    url: str
    url_canonical: str
    domain: str
    kind: SourceKind
    publisher_class: PublisherClass
    title: str | None
    language: str | None
    published_date: date | None
    published_precision: DatePrecision | None
    retrieved_at: datetime
    http_status: int | None
    content_type: str | None
    content_sha256: str | None
    size_bytes: int | None
    parse_outcome: ParseOutcome | None
    found_via: str                   # 'search:sq_…' or 'registry:who_gho'

class CrawlDecision(BaseModel):
    decision_id: str                 # cd_…
    run_id: str
    url: str
    domain: str
    outcome: CrawlOutcome
    rule: str | None                 # the robots line or header that decided it
    reason: str                      # human-readable, shown in DS-3
    robots_http_status: int | None
    decided_at: datetime
```

### 2.7 Slot result and run summary

```python
class SlotResult(BaseModel):
    run_id: str
    slot_id: str
    status: SlotStatus
    flags: set[SlotFlag]
    replans_used: int
    queries_tried: list[str]         # search_query ids
    sources_checked: list[str]       # source ids
    best_claim_ids: list[str]        # claims shown for this slot, ranked
    gap_note: str | None             # template text when status != answered

class RunSummary(BaseModel):
    run_id: str
    claims_extracted: int
    claims_dropped_quote: int
    claims_supported: int
    claims_refuted: int
    claims_insufficient: int
    claims_contested: int
    sources_fetched: int
    sources_blocked: int
    sources_unreachable: int
    sources_unreadable: int
    searches_used: int
    fetches_used: int
    tokens_in: int
    tokens_out: int
    cost_micro_usd: int
    wall_clock_ms: int
    by_model: dict[str, dict]        # tokens and cost per model id
```

---

## 3. Reference data

Reference data describes **no city's health** (A-09). It is loaded by scripts in `scripts/reference/` from files in `reference/`, versioned in the repo, and checked by the AT-02 scan for city-specific content.

### 3.1 Gazetteer

Source: GeoNames `cities15000` dump and `countryInfo` `[verify licence: expected CC BY 4.0; attribute in README]`. About 25,000 places with population of 15,000 or more `[verify count]`.

| Table | Loaded from | Key columns |
|---|---|---|
| `ref_place` | `cities15000.txt` | `gazetteer_id`, `name`, `ascii_name`, `alternate_names text[]`, `country_iso2`, `admin1_code`, `admin2_code`, `population`, `lat`, `lon`, `timezone` |
| `ref_admin1` | `admin1CodesASCII.txt` | `country_iso2`, `admin1_code`, `name` |
| `ref_country` | `countryInfo.txt` | `iso2`, `iso3`, `name`, `languages text[]` |

Search uses a trigram index on `ascii_name` and `alternate_names` (§4.6).

### 3.2 Slot catalogue

File `reference/slots.yaml`, loaded into `ref_slot`. Binding content:

| Slot | Dim | Question | Kind | Indicators or relations | Accepted levels |
|---|---|---|---|---|---|
| S01 | D1 | Which body runs public health in the city today? | relation | GOVERNS | city_wide |
| S02 | D1 | Has that body been reorganised or replaced recently? | relation | REPLACED_BY | city_wide |
| S03 | D2 | What share of adults has hypertension? | statistic | HTN_PREV | city_wide |
| **S04** | D2 | **What share of people with hypertension have it under control?** (headline) | statistic | HTN_CONTROL, HTN_TREATED, HTN_AWARE | city_wide |
| S05 | D2 | What share of adults has diabetes? | statistic | DM_PREV | city_wide |
| S06 | D2 | How many people die from cardiovascular disease or stroke? | statistic | CVD_MORT, STROKE_MORT, NCD_PREMATURE_MORT | city_wide |
| S07 | D3 | Which NCD or hypertension programmes operate in the city? | mixed | RUNS, OPERATES_IN | city_wide, sub_city_area |
| S08 | D3 | Is there primary-care screening for these conditions? | statement | — | city_wide, sub_city_area |
| S09 | D4 | Which national NCD plan and targets apply? | mixed | APPLIES_TO, ISSUED_BY | national, state_province, city_wide |
| S10 | D4 | Which hypertension treatment protocol is used? | statement | — | national, state_province, city_wide |
| S11 | D4 | What tobacco or salt policies apply? | statement | — | national, state_province, city_wide |
| S12 | D5 | Who leads the health authority? | relation | LEADS | city_wide |
| S13 | D5 | Which major hospitals and academic bodies are involved? | relation | PART_OF, PARTNERS_WITH | city_wide, metro_region |
| S14 | D5 | Which NGOs and partners work on these conditions? | relation | PARTNERS_WITH, FUNDS, RUNS | city_wide, metro_region |
| S15 | D6 | Is health data published at city level or below? | statement | — | city_wide, sub_city_area |
| S16 | D6 | Which health information system is used? | statement | — | national, state_province, city_wide |

Policy slots (S09–S11, S16) accept national levels as `answered`, because policy legitimately lives there. Statistic slots never do: a national figure for S03–S06 always yields `answered_wider_geo`.

### 3.3 Indicator catalogue

File `reference/indicators.yaml` → `ref_indicator`. The **comparability group** says which claims may be compared at all (R-35).

| Code | Name | Comparability group key | Notes |
|---|---|---|---|
| HTN_PREV | Hypertension prevalence | `indicator + threshold_code + measure_type + age band + sex` | Thresholds: `bp_140_90` (WHO), `bp_130_80` (ACC/AHA) |
| HTN_AWARE | Aware of their hypertension (of those with it) | same | Denominator must be people with hypertension |
| HTN_TREATED | Treated (of those with it) | same | |
| HTN_CONTROL | Controlled (of those with it) | same | Headline indicator |
| DM_PREV | Diabetes prevalence | `indicator + case_definition class + age band` | |
| CVD_MORT | Cardiovascular mortality | `indicator + unit + age standardisation stated` | |
| STROKE_MORT | Stroke mortality | same | |
| NCD_PREMATURE_MORT | Probability of dying 30–70 from main NCDs | `indicator` | WHO SDG indicator |
| POP_TOTAL | Population | `indicator + geography_level` | Context only |
| OTHER | Anything else numeric | never compared | |

`threshold_code` is set by code from `case_definition` using a small pattern table in `reference/thresholds.yaml` (for example `>=140` and `>=90` gives `bp_140_90`). If no pattern matches, `threshold_code` is `NULL` and the claim is not comparable.

### 3.4 Source registry (Wave 0)

File `reference/sources.yaml` → `ref_source`. Keyed by provider and indicator, **never by city**.

```yaml
- provider: who_gho
  adapter: structured.who_gho          # LLD-4 ports
  geography: national
  representativeness: modelled
  indicators:
    HTN_PREV:    { code: "<GHO indicator code, confirmed day 1>", age: [30, 79] }
    HTN_CONTROL: { code: "<GHO indicator code, confirmed day 1>", age: [30, 79] }
    DM_PREV:     { code: "<…>" }
    NCD_PREMATURE_MORT: { code: "<…>" }
- provider: dhs
  adapter: structured.dhs
  geography: [national, state_province]
  representativeness: representative_sample
  indicators: { HTN_PREV: { code: "<DHS indicator id, confirmed day 1>" } }
- provider: world_bank
  adapter: structured.world_bank
  geography: national
  indicators: { POP_TOTAL: { code: "SP.POP.TOTL" } }
```

Indicator codes for WHO and DHS are confirmed on day 1 `[spike]`; the loader refuses placeholder values.

---

## 4. PostgreSQL schema

Migrations create everything below in schema `c4c`. LangGraph's checkpointer creates its own tables in schema `lg` through its own setup call.

### 4.1 Reference tables

```sql
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE ref_country (
  iso2 char(2) PRIMARY KEY, iso3 char(3) NOT NULL UNIQUE,
  name text NOT NULL, languages text[] NOT NULL DEFAULT '{}'
);
CREATE TABLE ref_admin1 (
  country_iso2 char(2) REFERENCES ref_country, admin1_code text, name text NOT NULL,
  PRIMARY KEY (country_iso2, admin1_code)
);
CREATE TABLE ref_place (
  gazetteer_id text PRIMARY KEY, name text NOT NULL, ascii_name text NOT NULL,
  alternate_names text[] NOT NULL DEFAULT '{}',
  country_iso2 char(2) NOT NULL REFERENCES ref_country,
  admin1_code text, admin2_code text, population bigint,
  lat double precision NOT NULL, lon double precision NOT NULL, timezone text
);
CREATE INDEX ref_place_name_trgm ON ref_place USING gin (ascii_name gin_trgm_ops);
CREATE INDEX ref_place_alt_gin ON ref_place USING gin (alternate_names);

CREATE TABLE ref_slot (
  slot_id text PRIMARY KEY, dimension text NOT NULL, question text NOT NULL,
  short_label text NOT NULL,                     -- BD-03
  answer_kind text NOT NULL CHECK (answer_kind IN ('statistic','relation','statement','mixed')),
  indicator_codes text[] NOT NULL DEFAULT '{}', relation_types text[] NOT NULL DEFAULT '{}',
  headline boolean NOT NULL DEFAULT false, accepted_levels text[] NOT NULL
);
CREATE TABLE ref_indicator (
  code text PRIMARY KEY, name text NOT NULL, comparability_key text NOT NULL, notes text
);
CREATE TABLE ref_source (
  provider text PRIMARY KEY, adapter text NOT NULL, config jsonb NOT NULL
);
```

### 4.2 Cities, runs, events

```sql
CREATE TABLE city (
  city_id text PRIMARY KEY,
  gazetteer_id text NOT NULL UNIQUE REFERENCES ref_place,
  identity jsonb NOT NULL,                       -- CityIdentity
  latest_run_id text,                            -- set when a run ends completed or stopped_by_budget
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE run (
  run_id text PRIMARY KEY,
  city_id text NOT NULL REFERENCES city,
  status text NOT NULL CHECK (status IN ('queued','running','completed','stopped_by_budget','failed')),
  started_at timestamptz, finished_at timestamptz,
  budget jsonb NOT NULL,                         -- limits in force
  versions jsonb NOT NULL,                       -- model ids and prompt versions per role
  error text
);
CREATE INDEX run_city_idx ON run (city_id, started_at DESC);
ALTER TABLE city ADD CONSTRAINT city_latest_run_fk FOREIGN KEY (latest_run_id) REFERENCES run;

CREATE TABLE run_event (
  run_id text NOT NULL REFERENCES run,
  seq bigint NOT NULL,                           -- monotonic per run, from 1
  event_id text NOT NULL UNIQUE,
  type text NOT NULL,                            -- EventType
  payload jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, seq)
);

CREATE TABLE run_seq (                           -- per-run event counter (LLD-2 §10)
  run_id text PRIMARY KEY REFERENCES run,
  next_seq bigint NOT NULL DEFAULT 1
);

CREATE TABLE run_summary (
  run_id text PRIMARY KEY REFERENCES run,
  summary jsonb NOT NULL                         -- RunSummary
);

CREATE TABLE slot_result (
  run_id text NOT NULL REFERENCES run,
  slot_id text NOT NULL REFERENCES ref_slot,
  status text NOT NULL CHECK (status IN ('answered','answered_wider_geo','answered_negative','blocked','unreachable')),
  flags text[] NOT NULL DEFAULT '{}',
  replans_used int NOT NULL DEFAULT 0,
  queries_tried text[] NOT NULL DEFAULT '{}',
  sources_checked text[] NOT NULL DEFAULT '{}',
  best_claim_ids text[] NOT NULL DEFAULT '{}',
  gap_note text,
  PRIMARY KEY (run_id, slot_id)
);
```

`seq` is assigned in the same transaction that inserts the event, using a per-run counter row locked `FOR UPDATE` (LLD-2 §10). The stream endpoint replays `WHERE run_id = $1 AND seq > $last_event_id ORDER BY seq` (R-80).

### 4.3 Search, crawl, sources, snapshots

```sql
CREATE TABLE search_query (
  query_id text PRIMARY KEY, run_id text NOT NULL REFERENCES run,
  slot_id text NOT NULL REFERENCES ref_slot, query text NOT NULL, lang text NOT NULL,
  provider text NOT NULL, result_count int NOT NULL, replan_round int NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE crawl_decision (
  decision_id text PRIMARY KEY, run_id text NOT NULL REFERENCES run,
  url text NOT NULL, domain text NOT NULL,
  outcome text NOT NULL CHECK (outcome IN ('allowed','blocked_robots','blocked_content_usage',
    'blocked_login_or_paywall','blocked_private_address','unreachable_network',
    'unreachable_server_error','rate_limited')),
  rule text, reason text NOT NULL, robots_http_status int,
  decided_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX crawl_decision_run_idx ON crawl_decision (run_id, outcome);

CREATE TABLE source (
  source_id text PRIMARY KEY, run_id text NOT NULL REFERENCES run,
  url text NOT NULL, url_canonical text NOT NULL, domain text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('web_html','web_pdf','structured_api')),
  publisher_class text NOT NULL CHECK (publisher_class IN ('government','multilateral','academic','ngo','news','other')),
  title text, language text,
  published_date date, published_precision text,
  retrieved_at timestamptz NOT NULL, http_status int, content_type text,
  content_sha256 text, size_bytes int,
  parse_outcome text CHECK (parse_outcome IN ('parsed','unreadable','too_large','unsupported_type')),
  parsed_text text,                              -- normalised for display; offsets refer to this text
  found_via text NOT NULL,
  crawl_decision_id text REFERENCES crawl_decision,
  UNIQUE (run_id, url_canonical)                 -- fetch cache: one fetch per URL per run (HD-01)
);

CREATE TABLE snapshot (
  source_id text PRIMARY KEY REFERENCES source,
  content_gz bytea NOT NULL,                     -- raw bytes, gzip
  content_type text, sha256 text NOT NULL, size_bytes int NOT NULL,
  stored_at timestamptz NOT NULL DEFAULT now(),
  CHECK (size_bytes <= 10485760)                 -- 10 MB cap [tunable]
);
```

For `structured_api` sources, the snapshot holds the exact API response body and `parsed_text` holds a canonical JSON rendering of the record used, so the code check in HD-03 compares against stored bytes.

### 4.4 Claims and their details

```sql
CREATE TABLE claim (
  claim_id text PRIMARY KEY, run_id text NOT NULL REFERENCES run,
  city_id text NOT NULL REFERENCES city, slot_id text NOT NULL REFERENCES ref_slot,
  source_id text NOT NULL REFERENCES source,
  kind text NOT NULL CHECK (kind IN ('statistic','relation','statement')),
  statement text NOT NULL, quote text NOT NULL,
  quote_lang text NOT NULL, quote_translation text,
  span_start int NOT NULL, span_end int NOT NULL CHECK (span_end > span_start),
  -- required labels as columns (queried and indexed)
  geography_level text NOT NULL CHECK (geography_level IN ('city_wide','sub_city_area','sub_city_population',
    'metro_region','district','state_province','national','global')),
  geography_name text NOT NULL,
  measure_type text NOT NULL,
  reference_start date, reference_end date, reference_precision text,
  period_type text NOT NULL CHECK (period_type IN ('point_in_time','period','cumulative','publication_date_proxy')),
  representativeness text NOT NULL,
  -- optional labels
  optional_labels jsonb NOT NULL DEFAULT '{}',   -- population_*, setting, sample_size, case_definition,
                                                 -- threshold_code, method, denominator_text, denominator_stated
  flags text[] NOT NULL DEFAULT '{}',
  label_spans jsonb NOT NULL DEFAULT '{}',       -- BD-10: {"period": [start, end], ...} located label quotes
  geography_fit jsonb,                           -- BD-10: {relation, place_name, distance_km}
  status text NOT NULL CHECK (status IN ('extracted','dropped','supported','refuted','insufficient','contested','superseded')),
  extractor_model text NOT NULL, prompt_version text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX claim_city_slot_idx ON claim (city_id, slot_id, status);
CREATE INDEX claim_run_idx ON claim (run_id);

-- CHG-01: keyword route (LLD-5 §4.1). Maintained by the write node.
ALTER TABLE claim ADD COLUMN search_tsv tsvector;
CREATE INDEX claim_search_tsv_idx ON claim USING gin (search_tsv);

CREATE TABLE statistic (
  claim_id text PRIMARY KEY REFERENCES claim,
  indicator_code text NOT NULL REFERENCES ref_indicator,
  value_as_written text NOT NULL, value_num numeric, unit text,
  lower numeric, upper numeric,
  comparability_key text                         -- computed by code from labels; NULL = not comparable
);
CREATE INDEX statistic_cmp_idx ON statistic (comparability_key);

CREATE TABLE entity (
  entity_id text PRIMARY KEY, city_id text NOT NULL REFERENCES city,
  entity_type text NOT NULL CHECK (entity_type IN ('Place','Organization','Person','Programme','Policy','Indicator')),
  canonical_name text NOT NULL, normalized_key text NOT NULL,
  graph_uuid uuid NOT NULL UNIQUE,               -- uuid5 of entity_id
  attributes jsonb NOT NULL DEFAULT '{}',        -- e.g. organization subtype 'facility'
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (city_id, entity_type, normalized_key)
);
CREATE TABLE entity_alias (
  city_id text NOT NULL REFERENCES city, surface_form text NOT NULL,
  entity_id text NOT NULL REFERENCES entity,
  method text NOT NULL CHECK (method IN ('exact','normalized','acronym','embedding','model','human')),
  score real, created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (city_id, surface_form)
);

CREATE TABLE relation (
  claim_id text PRIMARY KEY REFERENCES claim,
  subject_entity_id text NOT NULL REFERENCES entity,
  relation_type text NOT NULL,
  object_entity_id text NOT NULL REFERENCES entity,
  valid_from date, valid_to date, valid_from_is_proxy boolean NOT NULL DEFAULT false
);

CREATE TABLE verdict (
  claim_id text PRIMARY KEY REFERENCES claim,
  label text NOT NULL CHECK (label IN ('supported','refuted','insufficient')),
  rationale text NOT NULL CHECK (length(rationale) <= 400),
  scope_verified boolean NOT NULL, period_verified boolean NOT NULL,
  verifier_model text NOT NULL, verifier_family text NOT NULL,
  fallback_used boolean NOT NULL DEFAULT false, prompt_version text NOT NULL,
  checked_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE consistency (
  claim_id text PRIMARY KEY REFERENCES claim,
  outcome text NOT NULL CHECK (outcome IN ('agrees','novel','conflicts','not_comparable')),
  compared_with text[] NOT NULL DEFAULT '{}', reason text NOT NULL
);

CREATE TABLE contested_pair (
  pair_id text PRIMARY KEY, claim_a text NOT NULL REFERENCES claim, claim_b text NOT NULL REFERENCES claim,
  headline_claim text NOT NULL REFERENCES claim,  -- picked by fixed rule (LLD-2 §5.4)
  reason text NOT NULL,
  review_status text NOT NULL DEFAULT 'open' CHECK (review_status IN ('open','resolved')),
  resolution_note text,
  CHECK (claim_a < claim_b), UNIQUE (claim_a, claim_b)
);

CREATE TABLE graph_link (
  claim_id text NOT NULL REFERENCES claim,
  edge_uuid uuid NOT NULL, written_at timestamptz NOT NULL DEFAULT now(),
  invalidated_at timestamptz,                    -- set when superseded
  PRIMARY KEY (claim_id, edge_uuid)
);
```

### 4.5 Answers and reports

```sql
CREATE TABLE answer (
  answer_id text PRIMARY KEY, city_id text NOT NULL REFERENCES city,
  run_id text NOT NULL REFERENCES run,           -- the run whose knowledge was used
  question text NOT NULL, question_type text NOT NULL,
  body jsonb NOT NULL,                           -- sentences with cited claim ids, badges, abstentions
  cited_claim_ids text[] NOT NULL DEFAULT '{}',
  graph_used boolean NOT NULL, models jsonb NOT NULL,
  conversation_id text,                          -- CHG-01: follow-up questions (LLD-5 §3.2)
  turn int NOT NULL DEFAULT 1,
  trace jsonb NOT NULL DEFAULT '{}',             -- CHG-01: retrieval trace (LLD-5 §10)
  created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX answer_conversation_idx ON answer (conversation_id, turn);

CREATE TABLE report (
  report_id text PRIMARY KEY, city_id text NOT NULL REFERENCES city,
  run_id text NOT NULL REFERENCES run, format text NOT NULL CHECK (format IN ('md','html','pdf')),
  content bytea NOT NULL, sha256 text NOT NULL, created_at timestamptz NOT NULL DEFAULT now()
);
```

### 4.6 Views used by the API

```sql
-- One row per fact the UI may show, with its full provenance (R-07, R-45; AT-12)
CREATE VIEW v_fact_evidence AS
SELECT c.claim_id, c.city_id, c.run_id, c.slot_id, c.kind, c.statement, c.quote, c.quote_lang,
       c.quote_translation, c.span_start, c.span_end, c.geography_level, c.geography_name,
       c.measure_type, c.reference_start, c.reference_end, c.period_type, c.representativeness,
       c.optional_labels, c.flags, c.status,
       s.value_as_written, s.value_num, s.unit, s.indicator_code, s.comparability_key,
       v.label AS verdict, v.rationale, v.verifier_model, v.fallback_used, v.prompt_version AS checker_prompt,
       src.source_id, src.url, src.title, src.publisher_class, src.published_date, src.retrieved_at,
       src.content_sha256, src.kind AS source_kind
FROM claim c
JOIN source src ON src.source_id = c.source_id
LEFT JOIN statistic s ON s.claim_id = c.claim_id
LEFT JOIN verdict v ON v.claim_id = c.claim_id;

-- Facts of a city's latest run that may be shown as facts
CREATE VIEW v_city_facts AS
SELECT f.* FROM v_fact_evidence f
JOIN city ON city.city_id = f.city_id AND city.latest_run_id = f.run_id
WHERE f.status IN ('supported','contested');
```

Contested claims appear in `v_city_facts` with the "Sources disagree" badge; refuted, insufficient, dropped and superseded claims never do.

---

## 5. Qdrant

### 5.1 Collection

| Setting | Value |
|---|---|
| Name | `source_chunks__{embedding_key}`, where `embedding_key` is a slug of provider and model (for example `openai_small_v1`). Changing the embedding model creates a new collection, so models are never mixed (R-82) |
| Vector size | `embedding.dimension` from config; validated at start-up against the provider's reported dimension |
| Distance | Cosine |
| Point ID | `uuid5(NAMESPACE, f"{source_id}:{chunk_index}")` so re-upserts are idempotent |

### 5.2 Payload

| Key | Type | Indexed | Purpose |
|---|---|---|---|
| `city_id` | keyword | yes | Every search filters by city |
| `run_id` | keyword | yes | Restrict to the latest run |
| `source_id` | keyword | yes | Provenance join |
| `slot_ids` | keyword[] | yes | Slots this source was fetched for |
| `chunk_index` | integer | no | Order within source |
| `char_start`, `char_end` | integer | no | Offsets into `source.parsed_text` |
| `text` | text | no | The chunk |
| `lang` | keyword | yes | |
| `publisher_class` | keyword | yes | Tier filter |
| `published_date` | datetime | yes | Recency filter |
| `is_table` | bool | no | Table chunks are whole tables |

### 5.3 Chunking

| Content | Rule |
|---|---|
| Prose | About 400 tokens with about 60 overlap `[tunable]`, split on sentence boundaries |
| Tables | One chunk per table, header row included; a table longer than about 1,200 tokens is split by rows with the header repeated in each chunk |
| PDF pages | Page boundaries kept in offsets so the evidence panel can show the page number |

Qdrant never holds verdicts or anything shown as a fact. A chunk reaches the user only as "mentioned in a source but not confirmed" (R-63).

### 5.4 Claim index

Added by CHG-01 (LLD-5 §4.2). `source_chunks__{embedding_key}` is now used only to find unconfirmed mentions; confirmed claims are found through this collection.

| Setting | Value |
|---|---|
| Name | `claim_index__{embedding_key}` |
| Point ID | `uuid5(NAMESPACE, claim_id)` |
| Embedded text | `statement` (always English) + `" | "` + `quote_translation` when present, otherwise `quote` |
| Payload | `claim_id`, `city_id`, `run_id`, `slot_id`, `kind`, `status`, `geography_level`, `indicator_code`, `reference_end` (keyword or date; indexed) |
| Written by | The write node, for every claim that becomes `supported` or `contested` |
| Updated by | Any status change: payload updated; points for `refuted`, `insufficient`, `superseded` are deleted |

---

## 6. Graphiti on Neo4j

### 6.1 Entity types

Declared as Pydantic models and passed to Graphiti as custom entity types. Attributes carry only what is needed for display and matching.

| Type | Attributes |
|---|---|
| `Place` | `entity_id`, `gazetteer_id` (when known), `level` (GeographyLevel) |
| `Organization` | `entity_id`, `subtype` (`government`, `facility`, `academic`, `ngo`, `funder`, `other`) |
| `Person` | `entity_id` |
| `Programme` | `entity_id`, `status` (`planned`, `piloting`, `running`, `ended`, `unknown`) |
| `Policy` | `entity_id`, `level` (GeographyLevel), `year` |
| `Indicator` | `entity_id`, `indicator_code` |

### 6.2 Relation types and allowed pairs

| Relation | From → To | Cardinality | Supersession rule |
|---|---|---|---|
| `GOVERNS` | Organization → Place | One current per place for public health | A newer supported claim end-dates the old edge |
| `REPLACED_BY` | Organization → Organization | Many | Never superseded |
| `PART_OF` | Place → Place; Organization → Organization | Many | Never superseded |
| `RUNS` | Organization → Programme | Many | Never superseded |
| `FUNDS` | Organization → Programme | Many | Never superseded |
| `PARTNERS_WITH` | Organization → Organization | Many | Never superseded |
| `OPERATES_IN` | Programme → Place | Many | Never superseded |
| `ISSUED_BY` | Policy → Organization | One | Never superseded |
| `APPLIES_TO` | Policy → Place | Many | Never superseded |
| `LEADS` | Person → Organization | One current per organization role | A newer supported claim end-dates the old edge |
| `MEASURED_IN` | Indicator → Place | Many | Never superseded; carries no value (R-87) |

Any other pair is refused by the write adapter before reaching Graphiti.

### 6.3 Write contract

One supported relation claim becomes one edge. Primary design `[spike]`:

```text
graph.upsert_entity(node)               # node.uuid = entity.graph_uuid, group_id = city_id
graph.add_triplet(subject_node, edge, object_node)
  edge.uuid        = uuid5(NAMESPACE, claim_id)
  edge.name        = relation_type
  edge.fact        = claim.statement
  edge.group_id    = city_id
  edge.valid_at    = relation.valid_from (or publication date, with valid_from_is_proxy)
  edge.invalid_at  = relation.valid_to
  edge.attributes  = { claim_ids: [claim_id], source_ids: [source_id], status: 'supported', proxy_date: bool }
→ insert graph_link(claim_id, edge.uuid)
```

**What the spike must confirm.** (1) Triplet writes keep our node UUIDs and do not trigger Graphiti's own entity resolution or model calls beyond embeddings. (2) Edge attributes are stored and returned by search. (3) Setting `invalid_at` on an existing edge works without deleting it.

**Fallback.** If (1) fails: write one compact episode per source listing that source's verified relations, with extraction instructions restricting types to §6.2, then map resulting edges back to claims by matching subject, relation and object names. Recorded as a decision if used.

**Supersession.** For `GOVERNS` and `LEADS`, before writing a new edge the write node finds the current edge with the same subject role and place or organisation. If the new claim's `valid_from` is later, it sets `invalid_at` on the old edge, sets `graph_link.invalidated_at`, and marks the old claim `superseded`. Nothing is deleted (R-44, R-60).

**Contested relations.** When two supported claims disagree on a `GOVERNS` or `LEADS` relation with overlapping validity, both edges are written with `status = contested` in their attributes, and a `contested_pair` row is created. Neither is end-dated.

### 6.4 Graph queries the system relies on

| Purpose | Query shape |
|---|---|
| Graph-only question 1 | Organizations with `RUNS` or `FUNDS` to a Programme that `OPERATES_IN` the city Place |
| Graph-only question 2 | Current `GOVERNS` edge into the city Place (`invalid_at IS NULL`), plus any `REPLACED_BY` chain from its subject |
| "As of" questions | Same queries with Graphiti's temporal filters on `valid_at` and `invalid_at` |
| Entity page | Neighbours of one entity, one hop, with edge facts and claim IDs |
| Analytics (COULD) | Export the city subgraph; degree and betweenness computed in the app |

---

## 7. Provenance queries

### 7.1 Evidence for one fact

```sql
SELECT f.*, sn.sha256 AS snapshot_sha256, sn.size_bytes AS snapshot_size
FROM v_fact_evidence f
LEFT JOIN snapshot sn ON sn.source_id = f.source_id
WHERE f.claim_id = $1;
```

Returns everything the evidence panel needs (AT-12). The highlighted passage is `source.parsed_text[span_start:span_end]`.

### 7.2 Evidence behind a graph edge

```sql
SELECT gl.claim_id FROM graph_link gl WHERE gl.edge_uuid = $1;
-- then 7.1 for each claim_id
```

### 7.3 Evidence behind a vector hit

The Qdrant payload carries `source_id`, `char_start` and `char_end`. The UI shows the chunk as "mentioned in a source but not confirmed", linking to the source and snapshot; it never shows it as a fact.

### 7.4 Coverage grid and gaps

```sql
SELECT sr.slot_id, rs.dimension, rs.question, rs.headline, sr.status, sr.flags, sr.gap_note,
       sr.replans_used, cardinality(sr.queries_tried) AS queries, cardinality(sr.sources_checked) AS sources
FROM slot_result sr JOIN ref_slot rs USING (slot_id)
JOIN city ON city.latest_run_id = sr.run_id
WHERE city.city_id = $1
ORDER BY sr.slot_id;
```

---

## 8. Data lifecycle

| Data | Lifetime | Mechanism |
|---|---|---|
| Reference data | Versioned in the repo | Reload script; idempotent |
| A city's runs | Kept; `latest_run_id` points at the newest completed or budget-stopped run | Re-research appends a new run, never overwrites |
| Snapshots | Kept with their source; 10 MB per source `[tunable]` | Oversized sources get `parse_outcome = too_large` and no snapshot |
| Failed runs | Kept for diagnosis; never become `latest_run_id` | |
| Rehearsal cities | Removed before the demo, except the named fallback city | `scripts/purge_city.py <city_id>`: deletes Postgres rows in dependency order, the city's Qdrant points by `city_id` filter, and the Graphiti partition by `group_id` |

---

## 9. Requirements covered

| Requirement | Where |
|---|---|
| R-07, R-13, R-45 evidence and provenance | §4.4, §4.6, §7 |
| R-08, R-33, R-89 labels, never inferred | §1.1, §2.3, `claim` columns |
| R-34, R-35 cascade and comparability | §3.3 comparability key, `statistic.comparability_key` |
| R-43 entity resolution | `entity`, `entity_alias` |
| R-44, R-60 time and churn | §6.2 supersession, `graph_link.invalidated_at` |
| R-47 claim lifecycle | `ClaimStatus` |
| R-55 snapshots | `snapshot` |
| R-56 code-located quotes | `span_start`, `span_end` |
| R-79 slots | §3.2, `slot_result` |
| R-80 replayable events | `run_event` with `seq` |
| R-82 one embedding model per store | Collection name includes `embedding_key` |
| R-84 run summary | `run_summary` |
| R-87 numbers owned by Postgres | `statistic`; `MEASURED_IN` carries no value |
| AT-12, AT-20, AT-21, AT-26, AT-32 | §7.1, §6.3, §3.3, `entity_alias`, `slot_result` |
| R-92 confirmed claims searchable by meaning | §5.4 claim index |
| R-93 keyword route | `claim.search_tsv` (§4.4), `entity_alias` |
| R-97 retrieval trace | `answer.trace` (§4.5) |

---

## 10. Decisions made in this part

| ID | Decision | Alternative | Reason |
|---|---|---|---|
| LD-01 | Prefixed ULIDs as IDs | UUIDv4 | Time-sortable, readable in logs and citations |
| LD-02 | One `source` row per URL per run | Global source table shared by runs | "Research always fresh"; evidence ties to exactly what this run saw |
| LD-03 | Required labels as columns, optional labels as JSONB | All JSONB | Required labels are filtered and indexed; optional ones vary |
| LD-04 | `value_num` parsed by code from `value_as_written` | Model returns the number | The model must not produce numbers it could alter; display always uses the written form |
| LD-05 | Badges and confidence computed at read time | Stored | They depend on what was asked and on thresholds that may be tuned |
| LD-06 | Entity identity owned by Postgres; Graphiti nodes use derived UUIDs | Graphiti resolves identity | Auditable; supports purge and re-runs (HD-06) |
| LD-07 | Collection name includes the embedding key | One collection | Changing models can never mix vectors |
| LD-08 | Policy slots accept national evidence as answered; statistic slots never do | Same rule for all | Policy legitimately lives at national level; prevalence does not |

## 11. Open items

| Item | Resolve by |
|---|---|
| GeoNames licence wording and attribution | Before loading reference data |
| WHO GHO and DHS indicator codes | Day-1 spike |
| Graphiti triplet behaviour (§6.3) | Day-1 spike |
| Embedding model ID and dimension | Day 1 |
| Thresholds: small sample, staleness | LLD-2 §7–8 |
