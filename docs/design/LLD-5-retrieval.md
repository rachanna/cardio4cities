# LLD Part 5: Retrieval for Reliable Answers

| | |
|---|---|
| **Version** | 1.0 |
| **Date** | 2026-10-03 |
| **Status** | Baseline for build. Introduced by change request CHG-01 (circulated as "CR-01"; renamed because `CR-xx` IDs are the content requirements in REQUIREMENTS §3) |
| **Replaces** | LLD-2 §15.1 steps 1–4 (classification, retrieval, bundle). LLD-2 §15.1 step 5 (post-check) stays and is extended in §9 here |
| **Inputs** | `REQUIREMENTS.md` · `HLD.md` §7 · `LLD-1` to `LLD-4` |

**Scope.** How a question about a researched city becomes a bundle of evidence that is complete, correctly scoped and verified, and how the answer built from it is checked. Retrieval in this system serves one goal: **reliable correctness**. A City Lead must be able to repeat the answer to an official.

**For Claude Code.**
- Retrieval code lives in `app/query/`. Routes are separate modules behind one interface (§4); fusion, anchoring and bundling are pure functions with unit tests.
- Every rule marked **binding** has an acceptance test (§13). Do not weaken one without a `DECISIONS.md` entry approved by the owner.
- Values marked `[tunable]` come from configuration (`retrieval.*`, §14).

---

## 1. Principles (binding)

1. **Retrieve facts, not text.** The evidence that can support a factual sentence is a confirmed claim. Page text can only ever appear as an unconfirmed mention.
2. **Recall from several independent routes; precision from code.** Four routes find candidates (§4). Code, not the model, decides what is in scope and what is verified (§5).
3. **Postgres has the final word.** Every candidate from Qdrant or Graphiti is re-checked against Postgres before it can enter the bundle. A stale index can never leak a refuted or superseded claim.
4. **If verified evidence exists for what was asked, it is in the bundle.** Slot anchors guarantee this independently of how well search worked (§6).
5. **Disagreement and scope travel with the fact.** Both sides of a conflict are always shown together; a figure for a wider area always arrives with the note that no city figure was found.
6. **Missing evidence is an answer.** The system abstains, using the stored gap record, instead of filling in.
7. **Every answer is traceable.** The full retrieval path is stored with the answer (§10).
8. **Measured before the demo.** A retrieval evaluation with hard gates (§12).

---

## 2. Pipeline

```text
question (+ optional conversation_id)
  → understand        classifier (model) + previous-turn hint (code)          §3
  → candidates        R1 structured · R2 keyword · R3 semantic · R4 graph      §4   (in parallel)
  → re-validate       Postgres: city, latest run, status, time scope           §5
  → fuse              reciprocal rank fusion, ties by the ranking key          §6
  → anchor            inject each requested slot's best claim, or its gap      §6
  → assemble          pairs kept together, diversity, size limits              §7
  → answer            answerer (model)                                         §8
  → post-check        code: citations, numbers, places, names, pairs, years    §9
  → store             answer + retrieval trace                                 §10
```

Latency target under about 15 seconds: classification about 1–2 s, routes in parallel under 1 s, answer 3–6 s, everything else in milliseconds.

---

## 3. Understanding the question

### 3.1 Classifier output (prompt `classifier@v2`, LLD-3 §6)

```python
class ClassifierOutput(BaseModel):
    question_type: Literal['figure', 'relationship', 'change_over_time', 'open', 'out_of_scope']
    slot_ids: list[str]                 # from the catalogue
    indicator_codes: list[str]
    entity_mentions: list[EntityMention]
    as_of: str | None                   # only if the user gave a date
    sub_questions: list[str] = Field(default_factory=list, max_length=3)  # for compound questions
    refers_to_previous: bool            # elliptical follow-up such as "and in the district?"
```

Validation (code): unknown slots and indicators removed; `as_of` must parse; `sub_questions` capped at 3.

### 3.2 Follow-up questions

- `POST /cities/{id}/ask` accepts an optional `conversation_id`. The server creates one when absent and returns it.
- The classifier receives the **previous turn's classification** (slots, indicators, entity mentions) as a hint, **not the previous answer's text**, so an error in one answer cannot be inherited by the next.
- **Merge rule (code):** when `refers_to_previous` is true, union the previous turn's slots, indicators and entities into this turn's, unless this turn names its own. Only the immediately previous turn is used.

### 3.3 Compound questions

When `sub_questions` is non-empty, each sub-question is classified as a slot set only (no extra model call; the classifier returns them together) and all routes run once over the union. The answer must cover each sub-question: the coverage check in §9 enforces it.

---

## 4. Candidate routes

All routes run in parallel. Each returns a ranked list of `(claim_id, rank, route)`; R3 also returns chunk mentions.

| Route | Store | Runs when | Finds |
|---|---|---|---|
| **R1 Structured** | Postgres `v_city_facts` | Any slot or indicator was identified | Confirmed claims for those slots or indicators, ordered by the ranking key (LLD-2 §5.2) |
| **R2 Keyword** | Postgres full-text on claims | Always (except out of scope) | Claims whose statement, translation, indicator name or entity names match the question's terms; exact on acronyms and numbers |
| **R3 Semantic** | Qdrant `claim_index__{key}`; secondarily `source_chunks__{key}` | Always (except out of scope) | Confirmed claims by meaning; separately, unconfirmed page passages as possible mentions |
| **R4 Graph** | Graphiti, city partition | `relationship`, `change_over_time`, or `open` with entity mentions | Edges for the requested relation types and entities, with time filters; mapped to claims through `graph_link` |

### 4.1 R2: keyword route

- A `tsvector` column on `claim`, `search_tsv`, holds `to_tsvector('simple', statement || ' ' || coalesce(quote_translation, '') || ' ' || coalesce(indicator name, ''))` plus entity canonical names for relation claims, maintained by code: written by the write node and refreshed on every status change. It is a plain column, not a generated one, because Postgres generated columns can read only their own row, and this text comes from `statistic`, `ref_indicator` and `entity` (LLD-1 §4.4). GIN index.
- The `simple` configuration is used on purpose: no stemming and no stop-word removal, so "STEPS", "NCD", "HEARTS", acronyms and numbers match exactly (RD-07).
- Query (BD-36; code review RV-066): `websearch_to_tsquery('simple', question)` ANDs every word and keeps stop words, so on development data 3 of 4 natural questions matched no showable claim. Code builds the query instead: the question's words, lower-cased, without the stop words listed in `reference/keyword_stopwords.yaml` (reference data, not city data), and without the city's own name, which every claim of the city shares; each remaining word becomes a quoted lexeme, and the lexemes are joined with OR (`to_tsquery('simple', 'a' | 'b' | ...)`). Acronyms and numbers stay exact. A question left with no word skips the route. Ranked by `ts_rank_cd`, so claims matching more of the words come first, top 20 `[tunable]`. Entity mentions are also matched with trigram similarity on `entity.canonical_name` and `entity_alias.surface_form` (≥ 0.4 `[tunable]`), adding the claims of matched entities.

### 4.2 R3: semantic route

**Claim index** (new Qdrant collection, LLD-1 §5):

| Setting | Value |
|---|---|
| Name | `claim_index__{embedding_key}` |
| Point ID | `uuid5(NAMESPACE, claim_id)` |
| Embedded text | `statement` (always English) + `" | "` + `quote_translation` when present, otherwise `quote` |
| Payload | `claim_id`, `city_id`, `run_id`, `slot_id`, `kind`, `status`, `geography_level`, `indicator_code`, `reference_end` (keyword or date; indexed) |
| Written by | The write node, for every claim that becomes `supported` or `contested` |
| Updated by | Any status change: payload updated; points for `refuted`, `insufficient`, `superseded` are deleted |

Search: the question text, filtered by `city_id`, `run_id = latest`, `status ∈ {supported, contested}`; top 20 `[tunable]`.

**Chunk search** (existing collection) runs only to find **mentions**: top 5 passages whose text did not become a confirmed claim. They never support a fact sentence.

**Cross-language.** Statements are always written in English by the extractor, so English questions find claims from any source language. The embedding model must be multilingual in every profile: the deployed OpenAI model is; the local Sentence Transformers model must be a multilingual model `[verify in the profiles task]` (RD-11).

### 4.3 R4: graph route

- Resolve entity mentions to entity IDs by lookup only (LLD-2 §6 steps 1–3; nothing is created).
- Search edges in the city partition restricted to the relation types for the requested slots; current edges only (`invalid_at IS NULL`), unless the type is `change_over_time` or `as_of` is given, in which case the time filter applies and end-dated edges are included.
- The fixed graph-only question templates (LLD-1 §6.4) are used when the classifier's slots match them.
- Each edge maps to its claims through `graph_link`.

### 4.4 Graph unavailable (RD-06)

If Graphiti fails, relationship and change questions do **not** fall back to the `relation` table in Postgres. They abstain with "relationship data is temporarily unavailable" and the trace records the failure. This keeps the graph genuinely load-bearing (R-05) and the failure honest. The graph switch (R-88) behaves the same way, deliberately.

---

## 5. Re-validation and scope (binding)

Every candidate claim ID from every route is joined to Postgres before anything else happens. A candidate is kept only if **all** hold:

| Check | Rule |
|---|---|
| City | `claim.city_id` = the asked city |
| Run | `claim.run_id` = `city.latest_run_id` |
| Status | `supported` or `contested`; plus `superseded` only when the type is `change_over_time` or `as_of` is set |
| Time | With `as_of`: the claim's reference period (or edge validity) includes or precedes `as_of`, and for each slot only the latest such claim is kept |
| Verdict | A verdict row exists (Wave 0 claims carry the code verdict) |

Every removal is counted by reason in the trace (§10). **Scope violations reaching the bundle must be zero** (gate in §12).

Wider-area figures are **not** removed: they are the honest fallback. They rank below city-level claims for the same slot (§6) and always carry the "Not city-level" badge.

---

## 6. Fusion and anchors

### 6.1 Reciprocal rank fusion

For each surviving claim: `score = Σ over routes 1 / (k + rank_in_route)`, with `k = 60` `[tunable]`. Ties are broken by the ranking key (LLD-2 §5.2), so trustworthiness decides between equally relevant claims.

### 6.2 Slot anchors: the recall guarantee (binding)

For every slot the question asked about (classifier slots, merged with the previous turn's and the sub-questions'):

- If the slot's `slot_result.status` is `answered` or `answered_wider_geo`: its first `best_claim_id` is **injected** into the candidate list if no route found it, and marked `anchored` in the trace.
- Otherwise: the slot's **gap record** (status, gap note, queries tried, sources checked) is attached, so the answer abstains for that slot using stored facts about the search.

Anchors make the bundle complete for every slot asked about, however well or badly the search routes did. Search quality then only affects *extra* context, never the core answer.

---

## 7. Bundle assembly (binding where marked)

1. Order: requested slots in the order asked; within a slot, fused score; claims for slots not asked about after those.
2. **Contested pairs travel together (binding).** If a claim in a contested pair is included, its partner is included immediately after it, whatever its score.
3. **Wider-area fallback travels with its gap (binding).** If a requested statistic slot is `answered_wider_geo`, its gap note is attached alongside the wider-area figure.
4. Diversity: at most 2 claims per slot, plus contested partners `[tunable]`.
5. Size: at most 8 facts and 4 mentions `[tunable]`. Mentions are added only for `open` questions with fewer than 3 facts.
6. Each fact carries its fact-card fields (LLD-4 §2.1): statement, value as written, geography, period, badge, confidence, contested partner ID, slot.

---

## 8. Answer generation (prompt `answerer@v2`, LLD-3 §7)

Unchanged in shape. Rules added to the system prompt:

- When evidence is marked contested, state both values with their sources and years. Never present one side alone.
- When a requested figure is only available for a wider area, say first that no city-level figure was found, then give the wider figure with what it describes.
- For a figure marked outdated, give its year.
- Each sentence that answers a sub-question names its `slot_id`.

---

## 9. Post-check (extends LLD-2 §15.1 step 5)

Code checks each sentence. Most failures remove the sentence and substitute an abstention; three are repaired deterministically instead, because the correct text is known.

| # | Check | On failure |
|---|---|---|
| 1 | Fact sentences cite at least one claim, all in the bundle | Remove; abstention for its slot |
| 2 | Every number in the sentence appears in a cited claim's value or quote | Remove; abstention |
| 3 | A figure for a wider area, stated for the city, carries its level word | Remove; abstention |
| 4 | **Names:** every proper name in the sentence (multi-word capitalised phrases and acronyms) appears in the question, a cited claim's statement or quote, or a cited entity's names | Remove; abstention (protects against invented people and organisations, AT-15) |
| 5 | **Contested completeness:** a sentence citing one side of a contested pair, without the other side cited anywhere in the answer | **Repair:** replace with the code template "Sources disagree: {value A} ({source A}, {year A}) and {value B} ({source B}, {year B})." |
| 6 | **Year for outdated figures:** a sentence citing an outdated claim does not contain its reference year | **Repair:** append "(as of {year})" |
| 7 | **Coverage:** a requested slot or sub-question has neither a fact sentence nor an abstention | **Repair:** append the slot's abstention from its gap record |
| 8 | Mention sentences contain fixed "not confirmed" wording | Remove |

Repairs use only stored values, never model text, so they cannot introduce errors. Each removal and repair is recorded in the trace, and the first-pass survival rate (sentences passing without action) is reported (§12).

---

## 10. Retrieval trace

Stored with every answer (`answer.trace`, JSONB) and shown to admins in the demo (DS-5, "why this answer"):

```json
{
  "classification": { "...": "ClassifierOutput", "merged_from_previous": ["S04"] },
  "routes": {
    "R1": { "candidates": [["clm_…", 1]], "ms": 12 },
    "R2": { "candidates": [["clm_…", 1], ["clm_…", 2]], "ms": 9 },
    "R3": { "candidates": [["clm_…", 3]], "mentions": [["src_…", 1840]], "ms": 210 },
    "R4": { "candidates": [], "ms": 95, "status": "ok" }
  },
  "removed": { "other_run": 2, "refuted": 1, "superseded": 0, "out_of_time": 0 },
  "fused": [["clm_…", 0.0484]],
  "anchored": ["clm_…"],
  "gaps_attached": ["S12"],
  "bundle": ["clm_…", "clm_…"],
  "post_check": { "removed": 1, "repaired": [{"check": 5, "claims": ["clm_…", "clm_…"]}], "first_pass_survival": 0.8 }
}
```

---

## 11. Failure modes

| Failure | Effect | Why the answer stays correct |
|---|---|---|
| Classifier misroutes the question | R1 misses | R2 and R3 still search everything confirmed; anchors cover any slot that was identified |
| Classifier identifies no slot | No anchors | R2 and R3 still find confirmed claims; post-check still applies; worst case an abstention |
| Embedding provider down | R3 empty | R1, R2, R4 continue; trace marks `R3: degraded` |
| Qdrant payload stale after a status change | A refuted claim is a candidate | Re-validation against Postgres removes it (§5) |
| Graphiti down | R4 empty | Relationship parts abstain honestly (§4.4) |
| Answer model invents a name or number | Post-check removes the sentence | Abstention from the gap record |
| Answer model shows one side of a conflict | Post-check repairs it from stored values | — |

---

## 12. Evaluation (binding gates)

### 12.1 Fixture set (runs in CI, no paid calls)

`tests/fixtures/retrieval/halden_bay/`: a fictional researched city with about 30 claims across all six dimensions, including:
- a contested pair (two comparable prevalence figures);
- a national-only figure for S04;
- an outdated figure;
- a superseded `GOVERNS` edge and its successor;
- a refuted claim and an insufficient claim (must never appear);
- an entity known by name and by acronym.

About 25 questions, each with gold claim IDs and an expected behaviour: `answer`, `abstain`, `disagree` or `wider_area`. In CI the classifier output is fixed per question and embeddings come from a deterministic fake embedder, so the tests check the plumbing and the rules exactly.

### 12.2 Real-model run (`poe eval-rag`, costs money; ask first)

The same questions with real models, plus about 15 questions on one real researched city with gold claims picked by the owner from the evidence panel.

### 12.3 Metrics and gates

| Metric | Definition | Gate |
|---|---|---|
| Scope violations | Bundle items failing any §5 check | **0** (hard) |
| Abstention correctness | Questions with no evidence that abstain; questions with evidence that do not | **100%** on fixtures |
| Contested completeness | Answers citing a contested claim that show both sides | **100%** |
| Citation validity | Fact sentences whose citations are in the bundle and whose numbers match | **100%** (enforced by post-check) |
| Bundle recall | Gold claims present in the bundle | ≥ 0.95 fixtures; ≥ 0.90 real |
| First-pass survival | Sentences passing the post-check without removal or repair | Monitored; below 0.8 means revisit the answer prompt |

---

## 13. Acceptance tests

| ID | Test | Requirement |
|---|---|---|
| AT-39 | A refuted claim present in Qdrant with a stale `supported` payload never reaches the bundle | R-95 |
| AT-40 | A question on a slot whose best claim no route returns still gets that claim (anchored) | R-94 |
| AT-41 | Citing one side of a contested pair yields both sides in the final answer | R-96 |
| AT-42 | An acronym question ("What does the GHS run?") finds claims about the full organisation name | R-93, R-43 |
| AT-43 | A question phrased differently from any claim's wording ("how many adults have high blood pressure") finds the prevalence claim through the semantic route | R-92 |
| AT-44 | A follow-up "and nationally?" after a city question on S03 retrieves S03 claims | R-98 |
| AT-45 | A sentence naming a person absent from the evidence is removed | R-08, AT-15 |
| AT-46 | Every answer stores a trace with routes, removals, anchors, bundle and post-check actions | R-97 |
| AT-47 | The fixture evaluation meets every gate in §12.3 | R-99 |

---

## 14. Configuration

```yaml
retrieval:
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

The local embedding model must be multilingual; start-up validation refuses a local Sentence Transformers model not on the configured multilingual list `[verify the model name in the profiles task]`.

Added by BD-38 (owner): `wall_clock_s: 45` and `max_cost_micro_usd: 50000`, one question's own budget.

### 14.1 As built (D3-2, BD-38)

| Part | As built |
|---|---|
| Code | `app/query/`: `understand.py`, `routes/` (`structured.py`, `keyword.py`, `semantic.py`, `graph.py`), `revalidate.py`, `fuse.py` (fusion and anchors), `bundle.py`, `postcheck.py`, `pipeline.py`, `llm.py`, `types.py`. `app/query` may not import `app/workflow`, so `app/api/asking.py` builds each question's dependencies, and the pure text normalisation (LLD-2 §4.1) and entity name keys moved to `app/domain/text.py` and `app/domain/entity_names.py` |
| Budget (owner) | Each question has its own budget ledger: `retrieval.wall_clock_s` (45) and `retrieval.max_cost_micro_usd` (50,000, $0.05). Every model call and the question's embedding reserve on it first. `limits.ask_per_min` is enforced per session. A refused or failed model call is 503 `dependency_unavailable` (`component: llm`) |
| Understanding | A date the user gave is read as its last day ("2023" is 2023-12-31). A follow-up takes the previous turn's slots, indicators and entities for whatever it names none of; a follow-up the classifier called out of scope takes the previous turn's type when it inherits slots. The classifier sees the previous classification as one line, never the previous answer |
| R2 | Entities are matched by alias, normalised key, trigram similarity (`r2_trigram_min`), or an acronym that is the initials of an entity's name (AT-42). Their relation claims follow the keyword matches |
| R3 | One embedding call per question. Mentions are chunks that hold no confirmed claim's quote span |
| R4 | Edges of the slots' relation types from the city partition by Cypher (no embedding call); with entity mentions resolved, only edges touching them (all edges when none resolved to a graph node). The two graph-only questions (LLD-1 §6.4) are these type-filtered reads |
| Graph off or down | For relationship and change questions, every claim except those of an asked slot that is not a relationship slot is set aside (counted as `graph_unavailable`), and relationship slots abstain with a fixed sentence (LLD-2 §15.3; RD-06) |
| Time scope | With a date: a relation must have started by then and not been ended (`superseded_on` or `valid_to`) by then; a statistic or statement must start by then, and only the latest per slot and indicator is kept |
| Bundle | An anchored claim goes first within its slot and is never cut by the size limits; a contested pair is added whole or not at all |
| Post-check | Check 2 skips a four-digit year written alone. Check 3 accepts the level word or the wider area's own name. Check 4 also allows the city, country and region names. Check 7 adds, for a slot whose confirmed fact is in the bundle, that fact's stored statement (after the wider-area gap note where it applies); otherwise the abstention. A removed sentence's slot gets its abstention when nothing else covers it. Abstentions keep one per slot |
| Trace | Also `stores_read` (Postgres, Qdrant, Neo4j; AT-11), `mentions` and the question's `budget`. `graph_used` is true when the graph route ran and succeeded |
| Golden set | `tests/prompts/golden/classifier.yaml` and `answerer.yaml`; answerer cases are graded after the real post-check (`scripts/eval_answers.py`); pass bars `eval.classifier_min`, `eval.answerer_min` |

---

## 15. Data changes (applied through LLD-1 by CHG-01)

| Change | Where |
|---|---|
| Column `claim.search_tsv` (plain `tsvector`, maintained by code) and GIN index | New migration |
| `answer.conversation_id`, `answer.turn`, `answer.trace` | New migration |
| Qdrant collection `claim_index__{embedding_key}` | LLD-1 §5; created at start-up like `source_chunks` |
| Write node upserts claim points; status changes update or delete them | LLD-2 §3.3 (`write`, `consistency`) |

---

## 16. Decisions made in this part

| ID | Decision | Alternative | Reason |
|---|---|---|---|
| RD-01 | Confirmed claims are the retrieval unit; page text only as labelled mentions | Chunk RAG | Only verified statements can support a fact |
| RD-02 | Four routes fused by reciprocal rank fusion | One semantic route | Independent routes fail differently; fusion is simple and needs no training |
| RD-03 | Slot anchors inject each requested slot's best claim or gap | Trust the search | Completeness for what was asked, independent of search quality |
| RD-04 | Every candidate re-validated against Postgres | Trust index payloads | A stale index can never leak a rejected fact |
| RD-05 | Contested pairs always travel together; repaired by template | Let the model choose | Showing one side of a conflict is a correctness failure |
| RD-06 | No fallback from Graphiti to the Postgres relation table | Fallback | Keeps the graph load-bearing (R-05); failure stays honest |
| RD-07 | Postgres full-text with the `simple` configuration for the keyword route | Qdrant sparse vectors; English stemming | Claims live in Postgres; exact matching for acronyms and numbers |
| RD-08 | No reranker in the PoC | Cross-encoder or model reranker | Small bundles ordered by trust; listed in the cut list with "bring back if measured misses" |
| RD-09 | Follow-ups use the previous turn's classification, not its answer text | Full chat history | An earlier answer's error cannot propagate |
| RD-10 | Deterministic repairs for contested pairs, missing years and missing coverage | Remove and abstain | The correct text is known from stored values |
| RD-11 | Multilingual embeddings in every profile | Model per environment without checks | Development results must reflect production |
