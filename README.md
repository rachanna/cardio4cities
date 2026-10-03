# CARDIO4Cities City Lead research assistant

Given a city name, researches the public web live, verifies what it finds, and produces a cited brief of the city's cardiovascular landscape. Design documents are in `docs/design/`; start with `CLAUDE.md`.

## Quick start (local)

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```text
copy .env.example .env      # then fill in values
uv sync
uv run poe up               # Postgres, Qdrant, Neo4j, SearXNG
uv run poe migrate          # database schema (needs DATABASE_URL only)
uv run poe reference        # gazetteer and reference data (needs DATABASE_URL only)
uv run poe lint
uv run poe test
```

`uv run poe` with no arguments lists every task. Database tests use `TEST_DATABASE_URL`
(default: the compose Postgres, database `c4c_test`) and skip when it is unreachable.

On Windows, use `127.0.0.1` rather than `localhost` in local URLs: `localhost` tries IPv6
first and each new connection waits for that to fail.

## Deploying to Render

`render.yaml` is a Render Blueprint: the app, Neo4j, Qdrant, Postgres and a keep-alive
cron, all in Singapore, with auto-deploy off. Deploy by hand, never on rehearsal or demo days.

1. In Render, install the GitHub app for this repository only.
2. New → Blueprint → this repository, branch `main`.
3. Enter the prompted secrets: `ACCESS_CODE` (12+ characters), `ADMIN_CODE` (different),
   `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `BRAVE_API_KEY`, `LANGSMITH_API_KEY`.
   Store passwords and `SESSION_SECRET` are generated.
4. Each deploy runs `scripts/predeploy.sh` (migrations and reference data) before the app starts.
5. Check from outside: `uv run poe smoke https://<service>.onrender.com`.

## Data credits

Place names, coordinates, populations, first-level regions and country languages come from
[GeoNames](https://www.geonames.org/), licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).
The data is used to identify the city a user names; it holds no health information.
Country languages are reduced to ISO 639-1 codes. See `reference/geonames/README.md`.

National health figures found before any web search (Wave 0) come from the
[WHO Global Health Observatory](https://www.who.int/data/gho), reused for non-commercial
purposes with acknowledgement of WHO as the source, and population from the
[World Bank World Development Indicators](https://data.worldbank.org/), licensed under
[Creative Commons Attribution 4.0](https://creativecommons.org/licenses/by/4.0/).
Every such figure names its source in the evidence panel.
