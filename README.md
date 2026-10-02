# CARDIO4Cities City Lead research assistant

Given a city name, researches the public web live, verifies what it finds, and produces a cited brief of the city's cardiovascular landscape. Design documents are in `docs/design/`; start with `CLAUDE.md`.

## Quick start (local)

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```text
copy .env.example .env      # then fill in values
uv sync
uv run poe up               # Postgres, Qdrant, Neo4j, SearXNG
uv run poe lint
uv run poe test
```

`uv run poe` with no arguments lists every task.
