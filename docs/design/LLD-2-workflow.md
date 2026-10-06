# LLD Part 2: Workflow and Algorithms

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-10-02 |
| **Status** | Baseline for build |
| **Inputs** | `REQUIREMENTS.md` v1.1 · `HLD.md` v1.0 (§5, §7, §8, §9) · `LLD-1-data.md` |
| **Read with** | `LLD-3-prompts.md` (model roles) · `LLD-4-interfaces.md` (ports, events, config) |

**Scope.** The LangGraph structure, shared state, every node's contract, and every deterministic algorithm: crawl gate, fetching, quote matching, number parsing, comparability, consistency, claim lifecycle, entity resolution, confidence, badges, slot status, budget, events, Wave 0, source selection, question answering and report assembly.

**For Claude Code.**
- Algorithms in §4–§14 are pure functions in `app/domain/` or `app/workflow/rules/`, with no I/O, so they are unit-tested directly.
- Every `[tunable]` value is read from configuration (`LLD-4` §5); the default shown is the starting value.
- Each section ends with the tests it needs. Write those tests with the code.

---

## 1. Module map

| Module | Holds |
|---|---|
| `app/workflow/graph.py` | Builds and compiles the main graph and the slot subgraph |
| `app/workflow/state.py` | `RunState`, `SlotState`, reducers |
| `app/workflow/nodes/` | One file per node; each node is a thin function calling rules and ports |
| `app/workflow/rules/` | Crawl gate, selection, quote matching, number parsing, comparability, consistency, slot status, gap notes |
| `app/domain/` | Types (LLD-1), confidence, badges, vocabulary mapping |
| `app/workflow/budget.py` | `BudgetLedger` |
| `app/workflow/limits.py` | Run-wide model and embedding concurrency wrappers; `StageClock` (busy time per stage) (BD-14) |
| `app/workflow/fetch_cache.py` | `FetchCache`: one fetch per URL per run, shared by slots (§14, BD-14) |
| `app/workflow/events.py` | `EventEmitter` |
| `app/query/` | Question answering (§15) |
| `app/report/` | Report assembly (§16) |

---

## 2. State

### 2.1 Run state (main graph)

```python
class RunState(TypedDict):
    run_id: str
    city: CityIdentity
    round: int                                   # 0 = first pass, 1–2 = re-plans
    all_slots: list[str]                         # every slot of the run: each ends with a status
    slots_to_work: list[str]                     # slot ids for the next fan-out
    replans: Annotated[dict[str, int], merge_dicts]             # slot_id -> re-plans used
    wave0_claim_ids: list[str]                   # Wave 0 claims, checked by code (HD-03)
    plans: Annotated[dict[str, SlotPlan], merge_dicts]          # slot_id -> queries for this round
    slot_reports: Annotated[dict[str, SlotReport], merge_dicts] # keyed '<slot_id>@<round>' (BD-14)
    finished: bool
```

```python
class SlotPlan(BaseModel):
    slot_id: str
    queries: list[PlannedQuery]                  # text, lang, purpose
    fallback: bool                               # template queries (§3.4)
    round: int                                   # only the current round's plans are sent

class SlotReport(BaseModel):                     # what one slot subgraph returns to the run
    slot_id: str
    round: int
    query_ids: list[str]
    source_ids: list[str]
    crawl_decision_ids: list[str]
    claim_ids: list[str]                         # every claim created this round
    supported_claim_ids: list[str]
    error: str | None
```

The state holds IDs only. Everything else is in Postgres, so a checkpoint stays small and a resumed run reads current data.

### 2.2 Slot state (subgraph)

```python
class SlotState(TypedDict):
    run_id: str
    city: CityIdentity
    slot_id: str                                 # the slot's definition is read from RunDeps
    round: int
    plan: SlotPlan
    query_ids: list[str]
    candidates: list[Candidate]                  # url, rank, query_id, publisher_class,
                                                 # names_other_place (BD-36: never title or snippet)
    reused: list[Candidate]                      # fetched by another slot this run (§14)
    allowed: list[Candidate]
    crawl_decision_ids: list[str]
    source_ids: list[str]
    drafts: list[Draft]                          # extracted, quote not yet located (BD-09)
    claim_ids: list[str]
    matched_claim_ids: list[str]                 # quote found
    supported_claim_ids: list[str]
    error: str | None
    slot_reports: dict[str, SlotReport]          # the subgraph's only output
```

Checkpoints hold this state (BD-14). Search titles and snippets never enter it: `search` decides the other-place flag itself (BD-36; code review RV-090, correcting BD-15(6)). Claim drafts do, until `match_quotes` writes the located ones.

### 2.3 Budget is not in state (decision WD-01)

Parallel slot branches would race on counters held in graph state. Budget lives in a process-level `BudgetLedger` keyed by `run_id` (§12), guarded by an `asyncio.Lock`, with its counters written to `run.budget.used` on every `budget_warning`, after every coverage round and at the end of the run. On resume, the ledger restores those saved counters, and its wall clock carries on from the saved value (BD-14).

---

## 3. Graph structure and node contracts

### 3.1 Main graph

```text
START → resolve_city ─┬→ wave0 → END (this branch only)
                      └→ plan_slots → [fan_out: Send(slot_subgraph) per slot in slots_to_work]
      → coverage ─┬─(needs_replan)→ plan_slots
                  └─(done)→ analytics → brief_ready → END
(plan_slots → coverage directly when no slot has a plan for the round)
```

**Wave 0 alongside planning (BD-27).** `wave0` and `plan_slots` run in the same step, so Wave 0's official-API calls overlap the planner call; the slot subgraphs start only when both are done, and coverage meets Wave 0's figures from the first round. Within a slot, `fetch_parse` fetches its pages side by side and `verify` checks its claims side by side (one claim per checker call), paced by the global fetch and model limits.

| Edge | Condition (code) |
|---|---|
| `fan_out` | `[Send("slot_subgraph", SlotState(...)) for slot_id in state["slots_to_work"]]` with a plan for this round; `"coverage"` when there is none |
| `coverage → plan_slots` | `route_after_coverage(state) == "replan"`: at least one slot qualifies for re-plan (§11.3) and the ledger allows a new round |
| `coverage → analytics` | otherwise |

`analytics` is a no-op when `analytics.enabled = false` `[tunable]` (COULD item).

### 3.2 Slot subgraph

```text
search → select_sources → crawl_gate ─┬─(none allowed)→ record_gate_gap → slot_done
                                      └─(some allowed)→ fetch_parse → extract → match_quotes
match_quotes ─┬─(none matched)→ slot_done
              └─(some matched)→ verify ─┬─(none supported)→ record_unsupported → slot_done
                                        └─(some supported)→ consistency → write → slot_done
```

These conditional edges make the three required routing points visible in the rendered graph: the crawl decision, the verdict, and (in the main graph) sufficiency (AT-03).

### 3.3 Node contracts

| Node | Kind | Reads | Writes | Events | Model | On failure |
|---|---|---|---|---|---|---|
| `resolve_city` | code | `city` row (created by the API before the run) | `run.status = running` | `run_started`, `identity_confirmed` | — | Run `failed` |
| `wave0` | code | `ref_source` | `source`, `snapshot`, `claim`, `statistic`, `verdict` | `wave0_finding` per claim | — | Log, continue: Wave 0 failure never stops a run |
| `plan_slots` | model | `ref_slot`; on re-plan, `slot_result` gap notes | `search_query` rows are written later by `search` | `slot_planned` per slot | Planner (LLD-3 §3) | Fallback: template queries from `ref_slot.question` + city name (§3.4) |
| `search` | code | plan | `search_query` | `search_done` | — | Slot report `error`; slot continues with zero candidates |
| `select_sources` | code | `search_query` results, run fetch cache | — (new URLs to the gate, cached ones to `reused`) | — | — | — |
| `crawl_gate` | code agent | candidates | `crawl_decision` | `crawl_decision` per URL | — | A URL whose gate errors is `unreachable_network` |
| `record_gate_gap` | code | decisions | — | — | — | — |
| `fetch_parse` | code | allowed | `source`, `snapshot`, Qdrant points | `source_fetched` or `source_unreadable` | Embeddings | Per-URL; failure recorded on `source.parse_outcome` |
| `extract` | model | `source.parsed_text`, in windows (BD-29) | claim drafts in slot state, no rows (BD-09) | `claim_extracted` | Extractor (LLD-3 §4) | Repair once, escalate once, else skip the window with `step_failed` (§17, BD-29) |
| `match_quotes` | code | claim drafts in slot state (BD-09) | `claim` rows for located quotes only, with `statistic`; for relation claims the resolved `entity`, `entity_alias` and `relation` (BD-12); a miss is recorded as a `claim_dropped` event with its reason and quote, never as a row (BD-09) | `claim_dropped` | Embeddings (entity merge) | — |
| `verify` | model | top claims (§5.3) + located passages | `verdict`, `claim.status` | `claim_verdict` | Checker (LLD-3 §5) | Retry, then labelled fallback model (§17) |
| `record_unsupported` | code | verdicts | — | — | — | — |
| `consistency` | code | this slot's supported relation claims, the run's supported and contested relation claims | `consistency`, `contested_pair`, `relation.superseded_on`, `claim.status`; claim-index payload status for contested claims | `conflict_found` | — | — |
| `write` | code | supported claims | Graphiti edges (names and fact embedded through the run's port, BD-36), `graph_link`, programme status; `claim.search_tsv`; Qdrant claim-index point (LLD-5 §4.2) | `fact_written` | Embeddings | Graph write failure: claim stays supported in Postgres, `graph_link` absent, event payload notes it; retried once at `brief_ready` |
| `slot_done` | code | subgraph state | returns `SlotReport` | — | — | — |
| `coverage` | code agent | all slot reports, claims | first the run-wide statistics sweep (§5.4: `consistency`, `contested_pair`, `claim.status`); then `slot_result` (one row per slot, replaced each round), `run.budget.used` | `conflict_found`; `slot_status` per slot worked this round | — | — |
| `analytics` | code | Graphiti subgraph | `entity.attributes.centrality` | — | — | Skip silently |
| `brief_ready` | code | everything | `run_summary`, `run.status`, `city.latest_run_id` | `run_finished` | — | — |

**Claim index (CHG-01).** Supersession (where a claim becomes `superseded`) and any change to `refuted` or `insufficient` after indexing delete the claim's index point (LLD-5 §4.2).

### 3.4 Planner fallback

If the planner fails validation twice, the slot gets two template queries: `"{slot.question_short} {city.name} {country_name}"` in English and the same template in the primary local language with the slot's local-language label taken from `reference/slots.yaml` (`labels_local` per language, generic) when present. This keeps a run moving without inventing anything.

**As built (BD-31; owner: English only for the PoC).** Validation is per slot: after the one repair, the slots of the last output that are usable on their own keep their plans, and only the others get the template (one slot's problem used to send all 16 to the template). The template is two English queries: `"{short_label} {city} {country}"` and `"{city} {short_label} survey report"`. Every planned query is in English.

---

## 4. Text algorithms

### 4.1 Quote normalisation and matching (R-56, AT-09)

**Normalise** (applied identically to source text and quote, building an offset map back to the original):

1. Unicode NFKC.
2. Map typographic quotes, dashes and non-breaking spaces to ASCII equivalents: `‘’‚‛ → '`, `“”„‟ → "`, `–— → -`, `U+00A0 → space`.
3. Remove soft hyphens (`U+00AD`) and zero-width characters.
4. Join line-break hyphenation: a letter, `-`, optional spaces, newline, optional spaces, a lowercase letter becomes the two letters joined.
5. Collapse every run of whitespace to one space; trim.

**Match:**

1. `nq = normalise(quote)`; reject if fewer than 3 or more than 60 words `[tunable]` (`quote.min_words_unique`, `quote.max_words`). A quote of 3 to 5 words (below `quote.min_words` = 6) is accepted only if it occurs exactly once; otherwise `dropped` with reason `quote_not_unique`, because taking the first of several occurrences could anchor a value to the wrong table row (BD-08). D2-3 checks that uniqueness within the extraction window the model was shown.
2. Find all occurrences of `nq` in `normalise(parsed_text)`, **case-sensitive, exact**.
3. Zero occurrences: status `dropped`, event `claim_dropped` with reason `quote_not_found`.
4. One or more: take the first; map back to original offsets for `span_start` and `span_end`.
5. **Statistic claims only:** `normalise(value_as_written)` must occur inside the matched quote. Otherwise `dropped` with reason `value_not_in_quote`.

No fuzzy matching under any circumstance. The run summary records the drop rate; a high rate means a parsing problem to fix, not a rule to loosen.

**Tests:** curly quotes vs straight; PDF hyphenation across lines; double spaces; a quote with one changed word (must drop); value present in source but not in quote (must drop); non-English quote matched in the original language.

### 4.2 Number parsing (LD-04)

`parse_value(value_as_written) -> (value_num | None, unit | None, lower | None, upper | None, unparsed: bool)`

| Pattern | Result |
|---|---|
| `21.7%`, `21.7 %`, `21.7 per cent`, `21.7 percent` | `21.7`, `percent` |
| `21,7%` (comma followed by 1–2 digits, no dot in the string) | `21.7`, `percent` (decimal comma) |
| `1,234,567` / `1.234.567` / `1 234 567` | `1234567`, `count` |
| `45 per 100,000` / `45 per 100 000` | `45`, `per_100k` |
| `20–25%`, `20-25 %`, `20 to 25 %` | `value_num = None`, `lower = 20`, `upper = 25`, `percent`. A range is never collapsed to a midpoint |
| `21.7% (95% CI 19.8–23.6)` | `21.7`, `lower 19.8`, `upper 23.6`, `percent` |
| `1 in 3`, `one third`, `about a fifth` | `None`, `unparsed = True` (flag `value_unparsed`) |
| Anything else | `None`, `unparsed = True` |

Ambiguous separators (`1,234` could be 1.234 or 1234) are resolved as thousands when exactly three digits follow and no other separator appears; otherwise `unparsed`.

**Tests:** each row above; negative cases such as `2019` alone (a year, not a value: `unparsed`).

**Since BD-33.** The value must stand as a whole number in the quote: no digit, or decimal part, runs on at either end, so "7%" is not found in "17%" or "7.5%" (still exact, never fuzzy). A thousands group never starts with zero, so "0.125" and "0,125" are decimals; a percentage with one separator before exactly three digits ("1.000%", "1,000 %") is never guessed and stays unparsed.

### 4.3 Threshold coding

`threshold_code(case_definition) -> str | None` using `reference/thresholds.yaml`:

| Pattern (on normalised, lower-cased text) | Code |
|---|---|
| systolic `>= ?140` or `≥ ?140` or `140/90`, or `< 140 … < 90` (control definition, BD-10) | `bp_140_90` |
| systolic `>= ?130` or `≥ ?130` or `130/80` | `bp_130_80` |
| fasting glucose `>= ?7.0 mmol` or `>= ?126 mg` | `fpg_7_0` |
| none matched | `None` |

**Threshold coding since BD-33.** "≥", "⩾", "≤" and "⩽" are read as ">=" and "<=" before matching; a number ends where no digit follows, so "≥140mmHg" matches; a rule may name an `exclude` pattern, and the blood-pressure rules never apply to a case definition about glucose (mg/dL, mmol, HbA1c). Comparability-key slugs drop accents but keep letters of every script, so two non-Latin district names no longer share an empty slug.

### 4.1a Label evidence and geography fit (BD-10)

After the quote is located, `match_quotes` applies two more code steps before writing the claim:

1. **Label quotes.** The extractor may copy the words that state the period, area or population when they lie outside the quote (`label_quotes`). Each is located in the same window with the §4.1 rules; a period quote must also contain each year of the labelled period. Located spans are stored on the claim (`label_spans`) and shown to the checker. An unlocated period or population label is cleared (the period then falls back to the publication-date proxy and is flagged); geography is required and never cleared.
2. **Geography fit.** `rules/geography_fit.py` relates the labelled area to the city using the gazetteer: `city` (the city, or a part of it), `contains_city` (its metro region, state, country, the world), `nearby` (a gazetteer place within `geography.nearby_km` `[tunable]`, 75), `elsewhere` (farther, or another state or country) or `unresolved` (the name cannot be placed). Rules for a local area name, in order (BD-17): (i) a qualifier (a segment after the first, as in "Halden Bay, Ostland") that is not the city's own region, district or country makes the figure not the city's; (ii) the full name is looked up before the name without area words, so a gazetteer place called "Greater X" or "X City" is that place; (iii) when other places of the country share the city's name, the figure is the city's only when the city's own region is named (as a qualifier, or anywhere in the source) and no namesake lies in that region, otherwise it is dropped (owner); (iv) when only the name without area words matches, the words removed decide: city, municipal or urban words mean the city, greater, metropolitan or district words mean an area containing it, rural, suburban or ward words mean neither and the figure is dropped; (v) a name merely containing the city's name counts only under (iv), so "North X" is dropped; (vi) places of one name on both sides of `nearby_km` are unresolved. National and state figures must name the city's own country or region exactly, never by containment ("South X" is not X). A national figure may also name the city's own region, since some countries are made of nations that the gazetteer lists as regions, or the country by its initials ("UK", "USA", a leading "the" ignored) or its ISO-3 code (BD-46). Names are compared through one normal form (`domain/place_names.place_key`), stored for every gazetteer name, ASCII name and alternate name in `ref_place.name_keys`. `elsewhere` and `unresolved` claims are dropped (`claim_dropped`, reason `geography_<relation>`) before verification. The fit is stored on the claim (`geography_fit`).

`effective_level(claim)` (`domain/geography.py`) is the level a claim counts as for the city: its labelled level, except that a `nearby` figure counts as at least `district`, and a figure about an area containing the city (`contains_city`) counts as at least `metro_region` even when labelled city-wide (BD-17). Gap notes name the effective level, or "a nearby place". Ranking (§5.3), badges (§8), confidence (§7) and slot status (§11) use it, so a nearby town's own city-wide figure is never shown as the city's.

### 4.1b Labels the evidence states (BD-22)

After the label quotes are located (§4.1a), `rules/label_evidence.keep_located` checks the labels' numbers against the located text: the quote and the located label passages. A number must stand as a whole number ("30" is not in "130" or "30.5"). Decimal commas and thousands separators are accepted as the source writes them, and a year may be the short end of a span ("2023-24"). Code clears, never guesses, and flags the claim `label_not_located`:
- an age band with an age the evidence does not state (both ages are cleared);
- a sample size the evidence does not state;
- a case definition whose numbers the evidence does not state, together with its threshold code, so it gets no comparability key;
- a stated period whose years the evidence does not state. It becomes a publication-date proxy. Before, an empty label quote was trusted as "stated in the quote".

A case definition with no numbers is left to the checker, which now sees it (LLD-3 §5).

**The area must be named (owner, BD-22).** A claim labelled `city_wide`, `metro_region` or `district` is dropped before checking, as `claim_dropped` / `geography_not_stated`, unless the located text names its area as whole words: the label as written, the label without area words, or, for the city itself, the city's name or ASCII name (`rules/geography_fit.area_named`). The city in the extractor's context is not evidence. Sub-city levels already need the city named (D2-4).

**Publication dates (BD-22).** Only page metadata dates a source (`extract_metadata(extensive=False)`): a year in the body text ("31 % in 2019", "Copyright 2014-2023") is never a publication date. `published_precision` is as precise as the page head writes the date (day, month or year), and `language` comes from `<html lang>` when the metadata gives none.

### 4.4 Comparability key (R-35)

```python
def comparability_key(stat: Statistic, labels: Labels, indicator: IndicatorDef) -> str | None:
    if stat.indicator_code == "OTHER" or stat.value_num is None:
        return None
    needs_threshold = stat.indicator_code.startswith("HTN_") or stat.indicator_code == "DM_PREV"
    if needs_threshold and labels.threshold_code is None:
        return None
    parts = [
        stat.indicator_code,
        labels.threshold_code or "-",
        labels.measure_type,
        f"{labels.population_age_min or '?'}-{labels.population_age_max or '?'}",
        labels.population_sex,
        labels.geography_level,
        slug(labels.geography_name),
        stat.unit or "-",
    ]
    if any(p.startswith("?") for p in parts[3].split("-")):
        return None                      # age band unknown: not comparable
    return "|".join(parts)
```

Two figures are comparable only if their keys are equal and not `None`.

**Added by BD-06 (AT-21).** A figure whose `measure_type` is a care-cascade or prevalence measure and whose denominator is not stated also gets `None`, so it is never compared with, or combined with, figures from other sources. The age band uses explicit `None` checks, so an age bound of 0 counts as stated.

**Tests:** 140/90 and 130/80 for the same city never share a key (F7); adults 18+ and 30–79 never share a key; unknown age band gives `None`.

---

## 5. Claim lifecycle and consistency

### 5.1 Lifecycle (R-47)

```text
extracted ──quote miss──────────────→ dropped
    │
    └─quote found─→ (ranked; top N verified)
                      ├─ supported ──consistency──→ supported | contested
                      │                                  └─(relation superseded later)→ superseded
                      ├─ refuted
                      └─ insufficient
Wave 0 claims: extracted → code record match → supported (verifier_model "code:record_match", family "code")
```

Claims beyond the per-slot cap stay `extracted`: kept, never shown, still searchable as text in Qdrant.

### 5.2 Ranking key (used everywhere a "best" claim is chosen)

Sort ascending by this tuple; the first element wins. Geography comes first since BD-36 (owner): with source tier first, five national government figures pushed a city survey out of the five checks per slot, and a WHO national figure headlined over an academic city survey.

1. Geography fit: 0 if the claim's effective `geography_level` is in the slot's `accepted_levels`, else the distance in the `GeographyLevel` order
2. Source tier: `government, multilateral` = 0, `academic` = 1, `ngo` = 2, `news` = 3, `other` = 4
3. Representativeness: `census` 0, `representative_sample` 1, `modelled` 2, `not_stated` and `not_applicable` 3, `non_representative` 4 (BD-22)
4. Recency: `-reference_end` (newer first; `NULL` last)
5. `claim_id` (determinism)

### 5.3 Verification cap

Per slot per round, matched claims are ranked by §5.2 and the top `verify.max_claims_per_slot = 5` `[tunable]` are sent to the checker. Wave 0 claims are never sent (HD-03).

### 5.4 Consistency for statistics

**Where it runs (BD-19).** Statistics are compared across the whole run, at the start of every `coverage` round, not inside a slot: each supported or contested statistic of the run (every slot, every round, Wave 0) is checked against all the others, and its outcome is stored in `consistency` (upserted, so a later round can change it). Slots run side by side, so a per-slot check would miss a figure another slot confirmed in the same round. A pair already contested is not contested again, and its `conflict_found` event is emitted once. A figure dated only by its publication date (`period_type = publication_date_proxy`) has no known period, so it counts as overlapping (BD-06(5)): two reports published in different years can still disagree.

For each supported statistic `c` with key `k`:

1. `k is None` → outcome `not_comparable` against same-indicator claims, reason lists which key parts differ or are unknown.
2. Find other `supported` or `contested` claims in the same run and city with key `k`.
3. None → `novel`.
4. For each match `o`:
   - Reference periods do not overlap → `novel` (a time series, not a conflict; the newer one ranks first by §5.2).
   - `|c.value_num − o.value_num| ≤ 0.5` percentage points for `percent`, or `≤ 2%` relative otherwise `[tunable]` → `agrees`.
   - Otherwise → `conflicts`: create `contested_pair(a, b)` with `headline_claim` = first by §5.2; set both claims to `contested`; event `conflict_found`.

### 5.5 Consistency for relations

For `GOVERNS` and `LEADS` (one current edge allowed): a new supported claim whose object (for `GOVERNS`) or subject (for `LEADS`) differs from the current edge's:

- Validity does not overlap and the new one is later → supersession (LLD-1 §6.3).
- Validity overlaps, or either validity is a proxy date within 12 months of the other → `conflicts`, contested pair, both written with `status = contested`.

All other relation types: identical subject, type and object → `agrees`; otherwise `novel`.

**Reading and ordering (BD-06).** For both `GOVERNS` and `LEADS`, two edges compete when they share the object (the place, or the organisation) and differ in subject. Because a current edge has no end date, ordering is decided in this order: the old edge ended on or before the new start → supersede; the new edge ended on or before the old start → the new claim is history (`superseded`); either start missing → `conflicts`; a proxy date within 12 months of the other → `conflicts`; explicit validity overlap → `conflicts`; new start in a later year → supersede; earlier year → history; same year → `conflicts`.

**Tests (§5):** two compatible prevalence figures 0.3 points apart (agrees); 4 points apart (contested, headline by tier); different survey years (both novel); 140/90 vs 130/80 (not comparable); a newer GOVERNS with a later valid_from (supersedes); two GOVERNS from the same year (contested).

---

## 6. Entity resolution (R-43, AT-26)

`resolve(city_id, surface_form, entity_type, source_text) -> entity_id`

1. **Alias hit.** `entity_alias(city_id, surface_form)` exists → return it (`method` unchanged).
2. **Normalised key.** `normalized_key = slug(casefold(strip_diacritics(surface_form)))` after removing a leading "the" and punctuation. Match on `(city_id, entity_type, normalized_key)` → register alias with `method = normalized`.
3. **Acronym map.** Before extraction results are resolved, code scans each source for `Long Name (ACR)` and `ACR (Long Name)` where `ACR` is 2–8 capital letters. Both forms are registered as aliases of one entity, `method = acronym`. A mention that is all capitals checks these aliases first.
4. **Embedding merge** (not for `Person`). Embed the surface form; compare with existing entities of the same type in the city. Cosine `≥ 0.92` `[tunable]` → alias, `method = embedding`, `score` stored. Between `0.85` and `0.92` → new entity, candidate pair logged for review (model adjudication is COULD). *Replaced by BD-24, below.*
5. Otherwise create a new entity with `graph_uuid = uuid5(NAMESPACE, entity_id)`.

The city itself is created as a `Place` entity at run start from the gazetteer identity, so every `OPERATES_IN`, `GOVERNS` and `APPLIES_TO` edge points at one node.

**Tests:** "Ghana Health Service", "GHS" and "the Ghana Health Service" resolve to one entity; two different people with similar names stay separate.

**As built (BD-12).** An alias hit counts only for the same entity type. An acronym pair is trusted only when the acronym is the initials of the long name and the source defines it one way. Candidate pairs are logged with entity IDs and score only. Relation claims are resolved in `match_quotes`, so their `relation` row is stored with the claim. A missing start date takes the publication date as a proxy only when that date is not after the stated end. The tests use fictional names (Norvania Health Directorate, NHD).

**Current order (owner, BD-24).**
1. An acronym the claim's own source defines resolves through its long form. The city-wide alias table is not consulted for it, so another source's alias for the same letters is never used.
2. Alias hit, for the same entity type.
3. Normalised key.
4. For `Organization`, `Programme` and `Policy`: the same significant words in any order (`word_set_key`; small words such as "of" and "the" are ignored). "Health Directorate of Norvania" is "Norvania Health Directorate"; "Halden Bay City Council" is not "Halden Bay District Council".
5. Otherwise a new entity.

Embedding similarity never merges. A pair at or above `entity.candidate_threshold` (0.85) `[tunable]` is only logged for review, with IDs and score. Places and people join only by exact alias or key, so "Greater Halden Bay" is never the city.

A name made only of generic words ("Department of Health", "City Council", "National Hypertension Control Programme"; `GENERIC_WORDS`, English only) could be any city's, state's or country's body. It joins only within its own source: its key carries the source ID, and no city-wide alias is registered for it.

---

## 7. Confidence label (R-48)

Computed at read time for supported or contested claims only.

| Component | Points |
|---|---|
| Source tier | government or multilateral 2 · academic 2 · ngo 1 · news 0 · other 0 |
| Representativeness | census or representative sample 2 · modelled 1 · not applicable 1 · non-representative 0 |
| Geography fit | level in the slot's accepted levels 2 · otherwise 0 |
| Recency | reference end within `confidence.recent_years = 5` `[tunable]` 1 · otherwise 0 |
| Denominator | stated, or not applicable to the measure 1 · not stated for a cascade or prevalence measure 0 |
| Verdict scope and period | both verified 1 · otherwise 0 |

Total out of 9: **High ≥ 7, Medium 4–6, Low ≤ 3**. Caps: a verdict from the same-family fallback is at most Medium; a `period_not_stated` claim is at most Medium. The label is returned with the list of components and points, which the evidence panel shows as reasons. Low facts never appear in the executive summary (HD-08).

**Tests:** a WHO national modelled figure for a city slot scores 2+1+0+1+1+1 = 6, so Medium; a city survey from government, recent, denominator stated, verified, scores 9.

---

## 8. Badges (R-78, AT-31)

Computed for a fact shown in the context of a city:

| Order | Badge | Condition |
|---|---|---|
| 1 | `not_city_level` | `geography_level` not in the slot's accepted levels; **or** `population_group` set and not one of `adults`, `all ages`, `general population`; **or** `setting` is `hospital`, `clinic`, `workplace` or `school` |
| 2 | `sources_disagree` | `status = contested` |
| 3 | `outdated` | statistics and statements: `reference_end` older than `badge.stale_years = 5` `[tunable]`; `LEADS` relations: older than `badge.stale_years_people = 2` `[tunable]` |
| 4 | `limited_sample` | `representativeness = non_representative`, or `sample_size < badge.small_sample = 300` `[tunable]` |

`main_badge` is the first condition that holds; `other_badges` are the rest. A sentence citing several claims takes the most severe main badge among them.

**Tests:** a national figure that is also old gets `not_city_level` as main and `outdated` as other.

---

## 9. Crawl gate and fetching (R-03, R-58, R-67, R-86)

### 9.1 Gate (runs before any content request)

For each candidate URL, in order; the first rule that applies decides:

| Step | Check | Outcome if it fails |
|---|---|---|
| 1 | Canonicalise: lower-case scheme and host, drop fragment, drop `utm_*` and similar tracking parameters | — |
| 2 | Scheme `http` or `https`; port 80 or 443 `[tunable]` | `blocked_private_address` (reason "unsupported scheme or port") |
| 3 | Resolve the host; every resolved address must be public (not private, loopback, link-local, multicast, reserved, or a cloud metadata address) | `blocked_private_address` |
| 4 | Fetch `robots.txt` for the origin (cached per run): timeout `fetch.robots_timeout_s` (15 s; was 5 s, raised after spike S-5, BD-07), max 500 KiB, up to 5 redirects, each redirect target's address checked | see 9.2 |
| 5 | Apply the robots rules for user agent `CARDIO4CitiesResearchBot`, else `*` | `blocked_robots` with the matching line in `rule` |
| 6 | Apply `Content-Usage` rules in the matched group, longest path wins: block on `ai-use=n` (draft-ietf-aipref-vocab-08), the earlier `ai=n` / `tdm=n`, or Cloudflare's `Content-Signal: ai-input=no`; `train-ai` and `search` opt-outs are recorded, not blocking (BD-07) | `blocked_content_usage` |
| 7 | Allowed | `allowed`, with crawl-delay recorded for the fetcher |

### 9.2 robots.txt status handling (RFC 9309)

| Status | Treatment |
|---|---|
| 2xx | Parse and apply. The text is decoded as UTF-8 with any byte order mark dropped, and a file longer than 500 KiB is applied from its first 500 KiB (BD-20) |
| 3xx | Follow up to 5 redirects; then as above. A redirect to a URL we never dial (scheme or port not allowed) is "Unreachable", outcome `unreachable_network` (BD-20) |
| 429 | "Unreachable", outcome `unreachable_server_error`: too many requests is not "no robots.txt" (owner, BD-20) |
| 4xx (including 401, 403, 404) | "Unavailable": no restrictions apply |
| 5xx, timeout or network error | "Unreachable": treat the whole site as disallowed; outcome `unreachable_server_error` or `unreachable_network`, so the slot reports it as unreachable, not blocked |

Checked against RFC 9309 when implementing (BD-07): §2.3.1.3 (4xx: crawlers MAY access any resources), §2.3.1.4 (5xx or unreachable: MUST assume complete disallow), §2.3.1.2 (follow at least five redirects), §2.5 (parse at least 500 KiB). Parsing uses an RFC 9309-compliant parser (Protego is the default choice `[verify]`); `Content-Usage` lines are parsed by our own small parser because general parsers ignore them.

### 9.3 Fetch rules

| Rule | Value |
|---|---|
| User agent | `CARDIO4CitiesResearchBot/0.1 (+<repo URL>)` |
| Per-domain concurrency | 1 |
| Per-domain spacing | `max(crawl_delay, fetch.min_interval_s = 1)` `[tunable]`. The budget is reserved before any wait, and only the domain is held while waiting, so one slow site never holds the global permits (BD-20) |
| Crawl-delay cap | A crawl-delay above `fetch.crawl_delay_cap_s = 30` `[tunable]` → `rate_limited` at the gate, no request; a wait that would run past the run's time left → `rate_limited`, nothing reserved (owner, BD-20) |
| Global fetch concurrency | `fetch.concurrency = 6` `[tunable]`, held only for the request itself |
| Timeouts | connect 5 s, read 20 s; a whole download at most `fetch.total_timeout_s` (60 s) and never past the run's time left (at least 1 s), else a timeout recorded as `unreachable_network` (BD-27) |
| Size | A `Content-Length` above 10 MB is refused before the body is read (BD-27); otherwise stop at 10 MB → `parse_outcome = too_large`, no snapshot. Counted on the decoded body as it streams in, and on the bytes received: we ask for `gzip, deflate` only and inflate a bounded amount at a time, so a compressed body never inflates past the cap; any other encoding is refused unread (BD-20) |
| Types | `text/html`, `application/xhtml+xml`, `application/pdf`, `text/plain`; JSON only for structured adapters |
| Redirects | Up to 5; **each new host goes through the gate again**; the connection uses the IP checked in step 3 (prevents DNS rebinding) |
| 401, 402, 403 on the page | `blocked_login_or_paywall`; body discarded unread |
| 5xx on the page | `unreachable_server_error`; body discarded unread, so the slot and the run summary count it as unreachable, as for robots.txt and official APIs (BD-35). Any other non-2xx (a 404) gives no source row and a `source_unreadable` event |
| 429 | Honour `Retry-After` up to 10 s and retry once; otherwise `rate_limited` |
| Response header `Content-Usage` with `ai=n` or `tdm=n` | Discard the body unread → `blocked_content_usage` |
| HTML with a password field and almost no text | `blocked_login_or_paywall`; body discarded, not snapshotted |

### 9.4 Parsing

| Type | Parser | Notes |
|---|---|---|
| HTML | Main-content extraction (trafilatura default `[verify]`) | Tables kept as text tables with headers. Decoded by `domain.charset` (BD-21): byte order mark, then the server's `charset`, then `<meta>`, then UTF-8 if valid, then windows-1252. `text/plain` the same, without `<meta>` |
| PDF | Text with page markers; table extraction (pdfplumber default `[verify]`) only on pages whose text contains target keywords for the slot | Page number kept in offsets. Read up to `fetch.pdf_max_pages` (200) pages. Parsing runs in a worker thread, off the event loop (BD-27) |
| Failure or under 200 characters of text | `parse_outcome = unreadable`, event `source_unreadable` | A parser never raises: a malformed or encrypted PDF, or HTML the libraries cannot read, gives empty text. The PDF `[page N]` markers do not count toward the 200 characters, so a scanned PDF is unreadable (BD-21) |

`parsed_text` is what offsets refer to. The snapshot holds the raw bytes.

**Tests (§9):** robots disallow (no content request made, AT-04); crawl-delay spacing (AT-05); `Content-Usage: ai=n` header; robots 404 (allowed); robots 503 (unreachable); redirect to a private address (refused, AT-23); 403 page (paywall outcome); 503 page (unreachable, BD-35).

---

## 10. Events (R-80)

### 10.1 Emitting

`EventEmitter.emit(run_id, type, payload)`:

1. In one transaction: `SELECT next_seq FROM run_seq WHERE run_id = $1 FOR UPDATE`, insert `run_event(seq = next_seq)`, increment `next_seq`.
2. After commit, push the event to the in-process stream (LangGraph custom stream writer) for live subscribers.

The counter table `run_seq` is defined in LLD-1 §4.2.

The stream endpoint always reads from Postgres after `Last-Event-ID`, then follows live events, so a reconnecting client sees every event once (AT-30).

### 10.2 Payloads

| Type | Payload |
|---|---|
| `run_started` | `run_id`, `city_id`, `budget` |
| `identity_confirmed` | `CityIdentity` |
| `wave0_finding` | `claim_id`, `indicator_code`, `value_as_written`, `geography_level`, `provider`; also `slot_id`, `year`, `status`, `graph_edge` (BD-34: the code used other names) |
| `slot_planned` | `slot_id`, `round`, `queries` (text and language) |
| `search_done` | `slot_id`, `query_id`, `result_count` |
| `crawl_decision` | `url`, `domain`, `outcome`, `reason` |
| `source_fetched` | `source_id`, `url`, `publisher_class`, `kind` |
| `source_unreadable` | `source_id`, `url`, `parse_outcome` |
| `claim_extracted` | `claim_id`, `slot_id`, `kind`, `statement` |
| `claim_dropped` | `claim_id`, `reason` |
| `claim_verdict` | `claim_id`, `label`, `verifier_model`, `fallback_used` |
| `conflict_found` | `pair_id`, `claim_a`, `claim_b`, `headline_claim` |
| `fact_written` | `claim_id`, `kind`, `graph_edge` (bool) |
| `slot_status` | `slot_id`, `round`, `status`, `flags`, `gap_note` |
| `budget_warning` | `counter`, `used`, `limit` |
| `step_failed` | `slot_id`, `round`, `stage` (`search`, `crawl_gate`, `fetch_parse`, `index_chunks`, `extract`, `match_quotes`, `verify`, `check`, or a node name when the whole node failed), `item` (query, URL, source and window, or claim ID; null for a whole node), `error` (the type, plus the message only for our own port errors, which never quote fetched text). BD-21 |
| `run_finished` | `status`, `summary` |

---

## 11. Slot status, re-planning and gap notes (R-79, AT-32)

### 11.1 Status

For slot `s` after a round, using all claims for `s` in this run:

```python
supported = [c for c in claims if c.status in ("supported", "contested")]
if any(effective_level(c) in s.accepted_levels for c in supported):   # BD-10
    status = "answered"
elif supported:
    status = "answered_wider_geo"
elif no source was fetched for s and s had crawl decisions:
    status = "blocked" if any(d.outcome.startswith("blocked") for d in decisions) else "unreachable"
else:
    status = "answered_negative"
```

As built (BD-46): for a statistic slot, only claims whose statistic is one of the slot's `indicator_codes` can make it `answered`; a supported claim for another indicator (`OTHER`, or a related measure such as prediabetes for a diabetes slot) is still shown, and the slot is `answered_wider_geo` when it has such claims and nothing better. `coverage` reads the indicators with `ResearchRepo.slot_indicators`.

### 11.2 Flags

`conflicting` when any contested pair involves the slot's best claim; `stale` when the best claim has the `outdated` badge.

### 11.3 Re-plan rule

A slot is re-planned when all hold:

- status is `answered_negative`, `blocked`, `unreachable`, or `answered_wider_geo` for a statistic slot;
- `replans_used < 2`, or `< 1` when the status is `answered_wider_geo` `[tunable]`;
- the ledger reports no `budget_warning` for searches, fetches or wall clock.

`route_after_coverage` returns `replan` when at least one slot qualifies; `slots_to_work` is set to those slots and `round` increments. Queries tried in earlier rounds are removed from the planner's output and from the template fallback; a slot left with no new query is not searched again (BD-14). Every round asks for `plan.queries_per_slot` (2) queries per slot; qualifying slots are re-planned in `replan.priority` order (S04, S03, S05, S06, then the rest in catalogue order), and only as many as the searches left can serve: `(budget.searches - searches used) // plan.queries_per_slot` (BD-15).

### 11.4 Gap notes (templates, HD-05)

| Status | Template |
|---|---|
| `answered_wider_geo` | "No city-level figure found. Best available is {level_word} ({geography_name}, {year})." |
| `answered_negative` | "Searched {n_queries} queries in {languages} and checked {n_sources} sources; nothing acceptable found for this question." |
| `blocked` | "{n} candidate sources refuse automated access ({top_reasons})." |
| `unreachable` | "{n} candidate sources could not be reached ({top_reasons})." |
| Claims found but none confirmed | append: " {n} claims were found but could not be confirmed against their sources." |
| Budget stopped allowed sources (BD-14) | append: " The run's budget ran out before {n} allowed sources could be read." Allowed but unread pages never make a slot `blocked` or `unreachable` |

`level_word` comes from a fixed map: `national` → "national", `state_province` → "state or regional", and so on.

**Tests:** a slot with only a national figure is `answered_wider_geo` and re-planned once; a slot whose only candidates were blocked is `blocked`; after a budget stop every slot still has a status.

---

## 12. Budget guard (R-50, R-61, AT-19)

```python
class BudgetLedger:
    async def reserve(self, kind: Literal["search", "fetch", "robots", "certificate", "model", "indexing"], est_tokens: int = 0) -> None: ...
    async def record_model(self, model: str, tokens_in: int, tokens_out: int, cost_micro: int) -> None: ...
    def phase(self) -> Literal["normal", "winding_down", "exhausted"]: ...
```

| Limit | Default `[tunable]` | At 85 % | At 100 % |
|---|---|---|---|
| Wall clock | 420 s (BD-15) | No new searches, fetches or re-plans | No new model calls; a call in flight is cut off (its timeout is the time left) |
| Searches | 64 (BD-15) | No re-plans | `reserve("search")` raises `BudgetExhausted` |
| Fetches | 60 | No re-plans | `reserve("fetch")` raises |
| Tokens | 1,500,000 (S-6, BD-15) | No re-plans | `reserve("model")` raises |
| Model cost | $3 (S-6, BD-15) | No re-plans | `reserve("model")` raises |

Every external call goes through `reserve` first. Nodes catch `BudgetExhausted`, stop new work for their slot, and return what they have. `coverage`, `analytics` and `brief_ready` call no external service, so they always run, and the run ends as `stopped_by_budget` with every slot carrying a status. A run ends `stopped_by_budget` when the ledger refused at least one reservation; a run that used its whole budget without a refusal is `completed` (BD-14).

`reserve("embedding")` covers chunk and entity embeddings (BD-30): refused at the wall clock or the cost cap like a model call, but not counted as one; every embedding call's estimated tokens and cost are recorded as `embeddings:<model>` and count towards the cost cap. Every model call's usage is recorded, including a failed call the provider billed (no structured output, a refusal), with its cached, cache-write and reasoning tokens.

`reserve("indexing")` covers the embedding calls that put a confirmed claim into the claim index and the graph (the claim-index point, the edge, a programme node's new status). It is counted but never refused, so a claim the checker confirmed just before a limit still reaches every store (BD-19); it costs only local or embedding calls, never a chat model.

At 85 % of the wall clock, `reserve("search")`, `reserve("robots")` and `reserve("fetch")` raise; model calls go on until a limit is reached, so claims in hand are still extracted and checked. Each counter emits one `budget_warning` the first time it passes `wind_down_at`.

Global concurrency limits, shared by every slot branch: model calls `llm.concurrency = 4`, embeddings `embeddings.concurrency = 4` `[tunable]` (`workflow/limits.py`); fetches `fetch.concurrency` with per-domain spacing (the collector); the search adapter releases about `search.rate_per_s` requests per second (Δ9). Slots themselves all run side by side.

---

## 13. Wave 0 (R-85, HD-03)

1. Look up `ref_source` providers. For each provider and indicator: call the structured-data adapter with the country code (and the city's first-level region for providers that support sub-national data).
2. For each indicator, take the most recent record for both sexes and the registry's age band. Since BD-34 the record must carry the registry's own indicator code, exactly one record may hold the latest year (two mean dimensions the registry does not name, so none is used), and a published value code cannot read gives no record rather than an older year. A year the provider did not publish is not a record.
3. Store the raw response as a `structured_api` source and snapshot. `parsed_text` is a canonical one-line rendering of the record used, for example `HTN_CONTROL | GHA | 2019 | both sexes | 30-79 | 12.3`.
4. Create a statistic claim whose `quote` is that rendering, `value_as_written` is the record's value as text, and labels come from the registry (`geography_level`, `representativeness`, age band, `method`). Code reads the value (`rules/wave0.record_value`): a bare decimal from the API is a number, and the registry unit is named as the parser names it (`%` is `percent`), so Wave 0 figures get a comparability key and meet web figures in §5.4 (BD-19). Any other form stays flagged unparsed.
5. **Code verification:** the record is re-read from the snapshot, and the claim's indicator, area, period and value must equal it exactly. Pass → `verdict(label = supported, verifier_model = "code:record_match", verifier_family = "code")`. Fail → `insufficient`.
6. Emit `wave0_finding`.

**Sub-national matching.** The region name from the provider must equal the city's `admin1_name` after normalisation (§6 step 2, plus generic region words), or appear in `reference/region_aliases.yaml` (owner-approved entries only). Otherwise the sub-national record is skipped, never guessed. No registry provider serves regions yet: DHS has no hypertension indicator in its API (BD-13).

**As built (BD-13).** Every API call goes through `Collector.fetch_api`: the gate's address checks and pinning apply, robots.txt does not (an official API is governed by its terms), and the decision is recorded as `allowed` with rule `api_terms:<provider>`. Adapters are pure (URL building, parsing), so code verification re-parses the stored snapshot with the same adapter. Population is stored as a source and creates no claim. One indicator's failure never stops the others.

**Tests:** a mocked WHO response produces a supported national claim with the right labels; an altered value fails the code check; an unmatched DHS region name is skipped.

---

## 14. Source selection (R-41, R-59)

1. Canonicalise and deduplicate all candidate URLs across the run (fetch cache: a URL already fetched in this run is reused, not refetched; a slot that wants a URL another slot is fetching waits for that fetch; the reusing slot extracts the stored source for its own question, BD-14).
2. Drop domains in `reference/publishers.yaml` `deny` (social media, question-and-answer sites, generic aggregators). This list is generic, never city-specific.
3. Classify publisher class by domain patterns in `reference/publishers.yaml`:
   - `government`: `.gov`, `.gov.*`, `.gob.*`, `.gouv.*`, `.go.*`, `.govt.*`, `.gv.*` and similar national patterns;
   - `multilateral`: `who.int`, `worldbank.org`, `un.org`, `unicef.org`, `dhsprogram.com`, `paho.org` and similar;
   - `academic`: `.edu`, `.ac.*`, `ncbi.nlm.nih.gov`, `europepmc.org` and a list of journal publishers;
   - `news`: a list of news publisher domains;
   - other `.org` domains: `ngo`; anything else: `other`.
4. API preference: if the domain has an entry in `publishers.yaml` `api` (for example an article site that offers an official API), route to that adapter instead of fetching the page (COULD for the PoC).
5. Rank by publisher tier, then the other-place rule, then search rank. **Other-place rule (BD-15):** a candidate whose search title, snippet or URL words name another gazetteer place of the country (population at least `select.other_place_min_population` = 15,000) and name neither the target city (any of its gazetteer names), its admin-1 region nor its country goes after the rest of its tier; it is never excluded, and national or state documents are unaffected. Search text only ranks; it never becomes evidence (R-58). Keep the top `select.max_new_urls_per_slot_round = 3` `[tunable]` (4 until BD-15: 16 slots x 4 pages reached the fetch wind-down in the first round and left no re-plan) not already fetched, and up to `select.max_reused_per_slot_round = 2` `[tunable]` already fetched (reused without a new gate decision).

---

## 15. Question answering (R-15, R-63, R-64, AT-28)

### 15.1 Steps

Steps 1–4 (understanding, routes, re-validation, fusion, anchors, bundle) are specified in `LLD-5-retrieval.md` §3–§7.

5. **Post-check** (code), per sentence:
   - `fact` sentences: `claim_ids` non-empty and all in the bundle's verified facts;
   - every number token in the text (regex for digits with separators, percentages, years excluded when followed by no unit) appears in the cited claims' `value_as_written` or quote after §4.1 normalisation;
   - if the sentence names the city with a figure whose claim is not `city_wide`, it must contain the level word from §11.4 (for example "national");
   - `mention` sentences cite a mention item and contain "not confirmed" wording from a fixed list.
   - **Failure:** the sentence is removed and replaced by an abstention for its slot (§15.2).
   - Extended by LLD-5 §9 (names, contested completeness, years, coverage).
6. **Badge** each surviving sentence with the most severe main badge among its claims.
7. Store `answer`; return.

### 15.2 Abstention text

"No confirmed {what} for {city}. {gap_note}" where `what` comes from the slot's short label and `gap_note` from `slot_result`. When no slot applies: "This isn't covered by the research for {city}."

### 15.3 Graph switch (R-88)

With the admin parameter `graph=off`, retrieval for `relationship` and `change_over_time` skips Graphiti and uses only Qdrant mentions. These cannot become facts, so the answer degrades to mentions or an abstention: this is the AT-10 demonstration.

**Tests:** an answer with an invented number is reduced to an abstention (AT-28); a national figure stated for the city without "national" fails the check; with the graph off, the graph-only question abstains.

---

## 16. Report assembly (R-17, HD-07, AT-18)

1. Load the latest run's slot results and `v_city_facts`.
2. **Summary:** for each dimension, the best fact per slot (§5.2) with confidence High or Medium, with its main badge.
3. **Dimension sections D1–D6:** every supported or contested fact per slot, ranked, each with badge, confidence and a numbered citation.
4. **Analysis:** model-written, at most 120 words per dimension `[tunable]`, given only that dimension's facts (LLD-3 §8); post-checked as in §15; on failure the paragraph is omitted.
5. **What we could not find:** every slot not `answered`, with its gap note.
6. **Handle with care:** facts with main badge `not_city_level` or `outdated` in the summary; `LEADS` edges supported by a single source; every contested pair.
7. **Sources:** numbered by first appearance; title, publisher, URL, published date, retrieved date.
8. **Run details:** run ID, date, status, models per role, counts from the run summary.
9. Render Markdown and HTML from templates; PDF through the renderer port. Store in `report`.

**As built (D3-3, BD-40):** `app/report/assemble.py` (pure) and `render.py` with Jinja2 templates; `app/api/reporting.py` writes the prose and `app/api/routers/reports.py` serves the download. Citations number sources by first appearance; a fact cites its source's number. A dimension with no slot researched in the run says so. Prose sentences are checked as answers are (cited facts of the section only, numbers and names from them; a gap sentence names no number its gap notes lack), cut at `report.intro_max_words`, and omitted under `report.min_paragraph_words`; analysis points must rest on summary facts. The report has its own budget ledger (`report.wall_clock_s`, `report.max_cost_micro_usd`, owner). On the first download of a run all three formats are generated and stored; later downloads serve them. The PDF is the same HTML without its head, laid out by fpdf2 with bundled DejaVu fonts (owner, BD-40).

**Layout (D4-3, BD-44):** the order of sections is:
1. **A cover table:** prepared for, researched, coverage and how to read it.
2. **At a glance:** key findings as a table (area, finding, confidence, caveats, reference) and coverage by area (city level, wider area only, not found, blocked or unreachable).
3. **Findings by area:** per question with findings, a table (finding, confidence, caveats, reference) and its wider-area note; the unanswered questions of that area named once.
4. **Analysis**, labelled as interpretation.
5. **Handle with care** and **What we could not find**, as tables; each gap note appears once.
6. **Sources:** the link text is the host and path; the link keeps the full URL.
7. **About this report:** a method paragraph written by code.
8. **Run details**, with models and prompt versions.

Headings use plain words, never slot or dimension codes. The reporter writes an introduction only for an area with at least one finding; an area with none gets a fixed sentence written by code. Gap notes pluralise ("1 source"). The PDF has a running title and "Page n of m".

---

## 17. Errors, retries and idempotency

| Situation | Handling |
|---|---|
| Search or fetch network error | One retry after 1 s; then record the outcome. Each search attempt reserves budget. A search that failed twice is not stored as a query tried (a re-plan may try it again) and emits `step_failed`. A fetch is retried only when the connection failed (`FetchError.retryable`): not after a timeout, which already used its whole time, nor for a certificate, a refused wait or an undecodable body (BD-21). robots.txt is retried the same way |
| Model 429 or 5xx | Up to 2 retries with backoff (1 s, 3 s) |
| Model output fails schema validation | One repair attempt (the validation error is sent back); extractor then escalates to its stronger model once; then the item is skipped with an event |
| Checker fails twice on the primary model | Exactly two calls on the primary (a failed attempt is not repaired; it counts), then the same-family fallback model, verdict marked `fallback_used = true` (R-82, BD-18). With no checker available the claim stays `extracted` and never becomes a fact |
| Exception inside a slot subgraph | Caught per item first (BD-21): one URL in `crawl_gate` or `fetch_parse`, one window in `extract`, one draft in `match_quotes` (labels that cannot hold, such as an inverted age band, drop the claim as `claim_dropped` / `invalid_labels`), one claim in `verify` (a claim already supported before the failure is kept). Each emits `step_failed` and the loop goes on. A failure of a whole node is caught by the node guard: `SlotReport.error` set, `step_failed` with no item, and the slot still gets a status from data so far. The run summary counts `step_failed` events by stage (`failed_steps`). Every vendor error is mapped to a port error in its adapter (model HTTP errors of any status, Qdrant upserts; a host name IDNA cannot encode does not resolve) |
| Two candidates redirect to one page | One source per canonical URL per run: the second insert is absorbed and the candidate reuses the stored source (`sources.source_at`); the fetch cache also remembers the final URL, and a resumed run seeds it with both URLs (BD-21). A source is shared with waiting slots as soon as it is stored; a failure to index its chunks in Qdrant is a `step_failed`, and extraction still reads its text from Postgres |
| Postgres unavailable | Run `failed`; the only fatal condition |
| Graphiti write fails | Claim stays supported in Postgres; retried once at `brief_ready`; if still failing, the graph-only demo question will show it, and the run summary records the count. The retry brings the graph in line with Postgres (BD-19): missing edges for supported, contested and superseded claims (a superseded claim's edge is written already ended on its stored `relation.superseded_on`, never current), edges of superseded claims still current, and contested marks that did not reach the graph |
| TLS certificate fails verification (BD-15) | Verification is never relaxed. The cause is named in the crawl decision (expired, self-signed, host name mismatch, issuer missing). When the server left out its intermediate, the certificate's own issuer (AIA) URLs are gated like any request (public address, pinned IP, budget kind `certificate`, spacing) and the issuer certificate is fetched once per run; the chain is then verified in code against the trusted roots with fetched certificates as untrusted intermediates, and only that verified chain's intermediates are used for the request (BD-16). Self-issued and non-CA certificates are never added; partial chains stay refused |
| Resume after crash | LangGraph checkpoint (Postgres, schema `lg`, thread ID = run ID) resumes the run once at start-up; all writes are idempotent: IDs are content-derived (`workflow/ids.stable_id`) or checked, Qdrant point IDs and graph edge UUIDs are derived from our IDs, inserts use `ON CONFLICT (<primary key>) DO NOTHING`, an event already stored is not appended again, and `verify` applies a verdict already stored instead of asking the checker again (BD-18). A run with no checkpoint, or already resumed once, is marked `failed` (BD-14). Ownership (BD-25): each run records its owner process and a heartbeat (`runs.heartbeat_s`); a process takes over a run only when its heartbeat is older than `runs.stale_after_s`, by one atomic update, and a partial unique index allows one active run in the database, so a deploy's new instance never runs the old instance's live run twice. A watcher in every process keeps its runs' heartbeat fresh and takes over quiet runs. Everything that can fail on a store (checkpoint read, dependencies, graph marker) comes before the claim, so an outage never spends the one resume, and nothing in the resume path raises out of start-up. On shutdown, runs are cancelled and awaited before the stores close: a cancelled run stays `running` with its checkpoint, for the next process (`runs.shutdown_grace_s`; uvicorn's graceful shutdown is bounded at 20 s). A stopped run stops (BD-28): every task a run starts carries its run ID, and when the run's task is cancelled those tasks are cancelled too and the ledger refuses every further external call, because LangGraph can leave a sibling node running when the cancel lands during a node's call. A connection error raised by a cancel is never retried. The fetch cache is seeded whichever step a slot resumes at, `fetch_parse` included |

---

## 18. Test map

| Area | Unit tests | Acceptance tests |
|---|---|---|
| Quote matching | §4.1 | AT-09 |
| Number parsing, thresholds, keys | §4.2–4.4 | AT-20, AT-21 |
| Lifecycle and consistency | §5 | AT-08, AT-20 |
| Entity resolution | §6 | AT-26 |
| Confidence and badges | §7, §8 | AT-13, AT-14, AT-31 |
| Crawl gate and fetch | §9 | AT-04, AT-05, AT-06, AT-23, AT-33 |
| Events | §10 | AT-30 |
| Slot status and re-plan | §11 | AT-16, AT-32 |
| Budget | §12 | AT-19 |
| Wave 0 | §13 | AT-01 (partial) |
| Question answering | §15 | AT-10, AT-15, AT-28 |
| Retrieval | LLD-5 | AT-39 to AT-47 |
| Report | §16 | AT-18 |

---

## 19. Decisions made in this part

| ID | Decision | Alternative | Reason |
|---|---|---|---|
| WD-01 | Budget in a process-level ledger, not graph state | Counters in state | Parallel branches would race |
| WD-02 | Routing edges at slot level (none allowed, none matched, none supported) | A graph edge per URL or claim | Visible, testable routing without an explosion of graph steps |
| WD-03 | A statistic's value must appear inside its quote | Value anywhere in the source | Ties the number to the exact passage the checker sees |
| WD-04 | Ranges are never collapsed to a midpoint | Midpoint | A computed number would not appear in any source |
| WD-05 | Different reference periods are a time series, not a conflict | Flag every difference | Avoids false "sources disagree" badges |
| WD-06 | `answered_wider_geo` statistic slots get one re-plan | None, or two | One more attempt at a city figure without burning the budget |
| WD-07 | robots.txt 5xx reported as unreachable, not blocked | Blocked | Different causes; the panel sees an honest reason |
| WD-08 | No person entities merged by embedding | Merge by similarity | Merging two people is worse than a duplicate |
| WD-09 | Confidence and badges computed at read time from stored labels | Stored | Thresholds can be tuned without migrations (LD-05) |

## 20. Open items

| Item | Resolve by |
|---|---|
| Exact RFC 9309 wording for 4xx and 5xx handling | When implementing the gate |
| Parser libraries (Protego, trafilatura, pdfplumber) behave as assumed | Day 1 |
| Token and cost caps | Spike S-6 (BD-14) |
| Thresholds: agreement tolerance, small sample, staleness, embedding merge | Tune during rehearsal |
