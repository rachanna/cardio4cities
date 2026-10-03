# CLAUDE.md

Read this first in every session. It is short on purpose; the design documents hold the detail.

## What this project is

An AI system that, given a city name at request time, researches the public web live, verifies what it finds, and gives a CARDIO4Cities City Lead a cited brief of the city's cardiovascular landscape: health figures, programmes, policies, stakeholders and gaps. It answers questions from verified evidence only and produces a downloadable report. Built as a case study for a panel that will name a city during a live demo.

**The design stance, in one line:** precision over coverage. A wrong or misattributed fact is a failure; an honest "not found" is a correct answer.

**The architectural stance:** the agent is the system, not the model. Models are used only where code reaches its limits (HLD §2.1). Everything checkable is checked in code.

## Where the truth lives

| Document | Use it for |
|---|---|
| `docs/design/REQUIREMENTS.md` | What must be true. Wins every conflict |
| `docs/design/HLD.md` | How the parts fit together |
| `docs/design/LLD-1-data.md` | Types, vocabularies, schema, Qdrant, Graphiti |
| `docs/design/LLD-2-workflow.md` | Graph, node contracts, every deterministic algorithm |
| `docs/design/LLD-3-prompts.md` | Model roles, prompts, output schemas |
| `docs/design/LLD-4-interfaces.md` | API, event stream, ports, config, errors, test map |
| `docs/design/LLD-5-retrieval.md` | Question answering: routes, re-validation, anchors, bundle, post-check, evaluation |
| `docs/design/REPO_STRUCTURE.md` | Where files go; dependency rules; commands |
| `docs/design/BUILD_PLAN.md` | Task order; each task lists the documents to load |
| `docs/DECISIONS.md` | Why things are the way they are; record new decisions here |
| `docs/design/BRAINSTORM.md` | Background reasoning; read only when a decision needs context |
| `docs/GIT.md` | Branch names, commit messages, secret scanning, submission tag |

Start each session by naming the task ID from `BUILD_PLAN.md` and reading the documents in its **Load** column.

## Non-negotiables (from the brief; never weaken)

1. Live research at request time. No city-specific data anywhere in code, prompts, config, reference files or fixtures.
2. LangGraph workflow that can be rendered and walked.
3. Crawl gate decides **before** any content request, and its decision has consequences.
4. Independent checker with consequences: refuted or insufficient claims never become facts.
5. Graphiti knowledge graph, genuinely used when answering questions.
6. Three distinct stores: Postgres, Qdrant, Graphiti on Neo4j, each on a real read path.
7. Evidence on every fact: source, exact passage, dates, geography, verdict, snapshot.
8. No fabrication. Never show national or other wider-area data as city data without the "Not city-level" badge.
9. Deployed and reachable at a URL.

## Rules that are easy to break by accident

- **Vendor SDKs only in `app/adapters/`.** Core code depends on ports. The import-lint test enforces this.
- **Never infer labels.** If the source does not state it, the field is empty and flagged.
- **Models never produce numbers.** They copy `value_as_written`; code parses it (LLD-2 §4.2).
- **No fuzzy quote matching.** Normalise both sides, then exact match (LLD-2 §4.1). If too many claims drop, fix parsing.
- **Search is links only.** Never enable a search provider's page-content features. Every page goes through the crawl gate.
- **Fetched text is untrusted.** Always wrapped and escaped by `app/prompts/safety.py`. Never logged.
- **Question answering never writes facts and never searches the web.**
- **Only confirmed claims support facts in answers.** Every candidate from Qdrant or Graphiti is re-checked against Postgres before use.
- **Both sides of a disagreement are always shown together.**
- **Statistic values belong to Postgres.** The graph links indicators and places but never stores or supersedes numbers.
- **Fixtures and prompt examples use the fictional city "Halden Bay, Norvania" only.**
- **Every `[tunable]` value comes from config**, never a literal in code.
- **Every external call goes through `BudgetLedger.reserve` first.**
- **Write events before streaming them.** The stream must replay from Postgres.

## How to work

1. Read the task's documents. If something is ambiguous, check `REQUIREMENTS.md`, then ask the owner rather than guess.
2. Write the tests the LLD lists for the task alongside the code. Acceptance tests carry their AT ID in the docstring.
3. Keep functions in `domain/` and `workflow/rules/` pure (no I/O) so they are unit-testable.
4. Run `uv run poe lint` and `uv run poe test` before finishing. A task is done only when its **Done when** checks pass.
5. If you deviate from the design, or a spike changes it, add a `BD-` row to `docs/DECISIONS.md` in the same change. If a change would weaken a MUST requirement, stop and ask.
6. Commit small, on a task branch, with messages that start with the task ID (`docs/GIT.md` §6).

## Commands

```text
uv run poe up          # local stores and SearXNG
uv run poe migrate     # database migrations
uv run poe reference   # load gazetteer and reference YAML (downloads GeoNames if missing)
uv run poe geonames    # download GeoNames only (needed by the AT-02 scan)
uv run poe dev         # API on :8000 and web on :3000
uv run poe test        # unit, contract, architecture, acceptance (recorded responses)
uv run poe lint        # ruff, mypy, import-linter
uv run poe fmt         # ruff format and auto-fix
uv run poe types       # regenerate web API types from OpenAPI
uv run poe spike NAME  # run a day-1 spike
uv run poe eval        # prompt golden set against real models (costs money: ask first)
uv run poe smoke URL   # smoke tests against a deployed URL
uv run poe purge CITY  # remove a city from all stores
uv run poe purge-graph # empty the local Neo4j graph and its embedding marker (local only)
```

Tasks live in `pyproject.toml` under `[tool.poe.tasks]` (BD-01); each is added by the build task that makes it work. `uv run poe` lists what exists.

## Do not

- Do not add city names, city URLs or city facts to any file in the repository, including tests.
- Do not call paid model or search APIs from tests; use recorded responses. Live calls only in spikes, `poe eval` and smoke tests.
- Do not commit `.env`, keys, access codes or downloaded GeoNames dumps.
- Do not add features the design does not list (maps, voice, chat persona, decorative graph views). Ask first.
- Do not turn on auto-deploy or deploy on rehearsal or demo days.

## Owner

Rachanna. Ask when a requirement and a design document disagree, when a spike result changes the design, before spending money on `poe eval`, and before any change that would weaken a MUST requirement.
