# Deployment notes

How to deploy CARDIO4Cities to Render, check it, run it and keep it safe until the demo. The design is in REPO_STRUCTURE §5 and the decisions in BD-04, BD-25 and BD-41.

**Rule:** auto-deploy is off. Deploy by hand from the Render dashboard, and never on a rehearsal or demo day (R-91).

---

## 1. What gets deployed

All services sit in Render region `singapore` on one private network. Only the app is public.

| Service | Kind | Plan | What it is |
|---|---|---|---|
| `c4c-app` | Web service, Docker | `1c-2g` | API, research runs and the web app at `/`. Pre-deploy `scripts/predeploy.sh`; liveness check `/api/v1/live` |
| `c4c-db` | Managed Postgres 16 | `basic-256mb` | The source of truth; private network only |
| `c4c-neo4j` | Private service, `neo4j:5.26.31-community` | `1c-2g`, 5 GB disk | Knowledge graph (Graphiti) |
| `c4c-qdrant` | Private service, `qdrant/qdrant:v1.19.1` | `0.5c-512mb`, 5 GB disk | Page chunks and the claim index |
| `c4c-keepalive` | Cron job, `curlimages/curl` | `0.5c-512mb` | Calls `/api/v1/health` every 6 hours |

Everything is declared in [`render.yaml`](../render.yaml) (a Render Blueprint).

**The app image** ([`Dockerfile`](../Dockerfile)) is built in two stages:
1. Node 22 builds the web app's static export (`web/out`).
2. Python 3.12 installs the app with `uv`, downloads GeoNames during the build, and copies the app, config, reference files and the web export.

**Container start** ([`scripts/start.sh`](../scripts/start.sh)):
- It builds `NEO4J_URI` and `QDRANT_URL` from the private services' hosts, then runs Uvicorn.
- It does not run migrations.

**Before each release** ([`scripts/predeploy.sh`](../scripts/predeploy.sh)):
- runs the migrations (`alembic upgrade head`);
- loads the GeoNames gazetteer;
- loads the reference YAML with `--strict`, so a placeholder indicator code stops the deploy.

**Deployed profile** ([`config/deployed.yaml`](../config/deployed.yaml)):

| Area | Setting |
|---|---|
| Planner, answerer, reporter | Claude Sonnet 5.5 |
| Extractor, classifier | Claude Haiku 4.5 |
| Checker | OpenAI `gpt-6.1-sol` (a different family, as required), with an Anthropic fallback that is labelled when used |
| Embeddings | OpenAI `text-embedding-3-small`, dimension 1536 |
| Search | Brave, links only, 5 requests a second |
| Per-run budget | 420 s, 64 searches, 60 fetches, 1.5M tokens, **$3.00** |
| Per-question budget | 45 s, $0.05 |
| Per-report prose budget | 120 s, $0.10 |
| Limits | 20 runs a day, 20 questions a minute, 30 city lookups a minute |

---

## 2. Before the first deploy

D3-5 (BD-42) closed the gaps found while writing these notes. One step remains, and it needs the Render service to exist:

| Item | Status |
|---|---|
| S-3 script in the image, with a writable `spike_results/` | Done |
| `poe purge CITY` (`scripts/purge_city.py`), in the image | Done |
| `/api/v1/health` checks the model, embedding and search providers, cached for 10 minutes, and lists prompt versions | Done |
| REPO_STRUCTURE §5 names `/api/v1/live` as Render's health check | Done |
| **The service URL.** The config and keep-alive assume `https://c4c-app.onrender.com` | **After §4.1:** if Render assigns another name, update `app.public_base_url` in `config/deployed.yaml` and the cron command in `render.yaml`, merge and redeploy |

---

## 3. Pre-flight checklist

Do these on the laptop before touching Render.

- [ ] `main` is green in CI, and the D3-5 fixes above are merged.
- [ ] The image builds locally: `docker build -t cardio4cities:check .`
- [ ] The accounts have credit: Anthropic, OpenAI, Brave Search.
- [ ] You have decided the **spend cap for the first live run**. The run cap is $3.00; S-6 measured $0.55 to $1.10 in model cost plus about $0.24 in searches.
- [ ] You have chosen two codes:
  - `ACCESS_CODE`: at least 12 characters; given to the panel.
  - `ADMIN_CODE`: different from `ACCESS_CODE`; only for the presenter. It unlocks the workflow diagram, the graph switch and answer traces.
- [ ] The secrets are ready to paste into the dashboard: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `BRAVE_API_KEY`. **Never put them in the repository, a chat or a ticket.**
- [ ] It is not a rehearsal or demo day.

---

## 4. First deployment

### 4.1 Create the services from the Blueprint
1. Render dashboard → **New** → **Blueprint** → choose the `cardio4cities` repository, branch `main`.
2. Render reads `render.yaml` and lists the five services, the database and the env group `c4c-stores`.
3. Enter the values marked `sync: false`: `ACCESS_CODE`, `ADMIN_CODE`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `BRAVE_API_KEY`.
4. Leave the rest to the Blueprint:
   - `SESSION_SECRET` and the store passwords are generated;
   - `DATABASE_URL` and the store hosts are wired automatically.
5. Apply. If Render refuses the `basic-256mb` Postgres plan (it's a legacy plan ID), choose the smallest current Postgres plan and record the change in a BD row.

### 4.2 Watch the first build
The order is: database and private services start → app image builds → pre-deploy runs → app starts.

| Stage | What to expect | If it fails |
|---|---|---|
| Image build | The Node stage runs `npm ci` and `next build`; the Python stage installs packages and downloads GeoNames. Several minutes the first time | Read the build log. A failed GeoNames download means the GeoNames site was unreachable: retry the build |
| Pre-deploy | Migrations up to the latest one, then GeoNames rows, then `ref_indicator`, `ref_slot`, `ref_source` counts | `--strict` failing means a reference file still holds a placeholder code. Fix it in the repository; never remove `--strict` |
| Start | Uvicorn starts. Start-up validation runs before it accepts traffic | See §8. The log names the failing setting without revealing secrets |

### 4.3 Note the real URL
Copy the service URL from the dashboard. If it isn't `https://c4c-app.onrender.com`, apply gap 4 from §2 and redeploy.

---

## 5. Checks after every deploy

Run these in order. The first three cost nothing.

1. **Liveness:** `curl -fsS https://<app-url>/api/v1/live`
2. **Health:** `sh scripts/keepalive.sh https://<app-url>`
   - `status` should be `ok`, with every component `ok`:
     - the stores: `postgres`, `qdrant`, `neo4j`, `reference_data` (16 slots);
     - the providers: `llm_anthropic`, `llm_openai`, `embeddings`, `search`;
   - providers are checked at most every 10 minutes, so a fixed key can take up to 10 minutes to show `ok`;
   - `versions.prompts` lists the prompt version of each role;
   - `checker_independence` should be `different_family`;
   - the body must show no hosts or keys.
3. **Smoke tests from outside** (AT-17, AT-29 partial): `uv run poe smoke https://<app-url>`. They check:
   - the web app is served at `/`;
   - health is `ok` from outside;
   - health reveals no hosts or keys;
   - API errors use the JSON envelope.
4. **Sign-in:** open the URL on a laptop and on a phone, and sign in with `ACCESS_CODE`. The phone half of the D3-4 walkthrough happens here.
5. **One live research run.** This costs money, within the cap you set in §3.
   - Type a city, check the "You chose …" identity, then click **Research**.
   - Watch the live progress until the run finishes. Every slot must end with a status.
   - Open the brief and one evidence drawer, ask two questions (one that should be answered and one that should abstain), and download the PDF.
   - Read the cost in the run summary and record it.
6. **Keep-alive:** in the dashboard, trigger `c4c-keepalive` once and confirm it exits 0.

---

## 6. Spike S-3: reachability from the deployed host

This must happen before the first rehearsal (BD-36). It makes no model or search calls, so it costs nothing.

1. Render dashboard → `c4c-app` → **Shell**.
2. Create the sites list, one URL per line. It is git-ignored and never enters the repository:
   ```sh
   mkdir -p spike_results && cat > spike_results/s3_sites.txt <<'EOF'
   # paste the site URLs here
   EOF
   ```
3. Run `python -m scripts.spikes.reachability`.
4. **Copy the printed summary before closing the shell.** The container's disk is wiped on the next deploy, and `spike_results/S-3-reachability.md` goes with it.
5. Record the summary in a BD follow-up row in `docs/DECISIONS.md`: the APIs by name, and the sites counted by outcome. Real site URLs stay out of the repository.

---

## 7. Routine operations

### Redeploying
1. Merge to `main`, with CI green.
2. Check that no run is in progress (the start screen or `GET /api/v1/runs/{id}`).
3. Dashboard → `c4c-app` → **Manual Deploy** → **Deploy latest commit**.
4. Run the checks in §5, steps 1 to 3.

If a run *is* in progress during a deploy:
- the old process has 20 seconds to stop;
- the run is saved at its last checkpoint and resumed once by the new process;
- a second interruption marks the run failed.

### Rolling back
Dashboard → `c4c-app` → **Events** → pick the previous deploy → **Rollback**.

**Migrations only go forward.** A rollback to code older than the newest migration may fail at start-up. Prefer fixing forward; roll back only when the newest deploy added no migration.

### Removing a city
From the `c4c-app` shell (locally, `uv run poe purge` with the same arguments):
1. `python -m scripts.purge_city --list` shows each city's ID, name and run count.
2. `python -m scripts.purge_city CITY_ID` is a dry run: it lists what would be deleted and deletes nothing.
3. `python -m scripts.purge_city CITY_ID --yes` deletes the city from Qdrant, Neo4j, Postgres and the LangGraph checkpoints.

It refuses a city with a queued or running run. If a store fails partway, run the same command again: Postgres is cleared last, so the city is still found.

**At the freeze (D4-7):** purge every rehearsal city except the fallback city.

### Rotating secrets
1. Change the value in the dashboard: `ACCESS_CODE`, `ADMIN_CODE`, or a provider key.
2. Redeploy.

Changing `SESSION_SECRET` signs everyone out. Change the access codes after the demo.

### Costs to watch
- **Render:** compute is billed by the second for every service. The private services and the database cost money even when idle, so suspend or delete them after the assessment if they are no longer needed.
- **Models:** at most $3.00 a run, $0.05 a question and $0.10 per report's prose. At most 20 runs a day, so the worst case is $60 a day in run budgets. Lower `limits.runs_per_day` if that is too high.
- **Brave:** each search is billed; a run makes at most 64.

---

## 8. Troubleshooting

| Symptom | Likely cause | What to do |
|---|---|---|
| App won't start; log lists config problems | Start-up validation: a missing secret, a placeholder in `deployed.yaml`, a checker in the same family as the extractor | Fix the named setting; never weaken the check |
| App refuses to start: graph embedding marker mismatch | The Neo4j graph was built with another embedding model | On a fresh deploy this can't happen. Locally, `poe purge-graph` (it refuses on `deployed`) |
| Neo4j won't start | An unknown `NEO4J_*` variable | Store credentials must keep the `STORE_` prefix (BD-04) |
| `/health` is `degraded` | One store is down or slow (3-second limit per check) | Open that private service's logs in the dashboard |
| Sign-in returns 429 | 5 failed attempts from one address in 10 minutes | Wait 10 minutes. The limit keys on `CF-Connecting-IP` |
| Start says a run is already in progress (409) | One run at a time per deployment | Open the run that's in progress; wait for it to finish |
| A run ends `stopped_by_budget` | The time or cost limit was reached | Expected. Every slot still has a status; the summary says why |
| Many sources are "unreachable" | Certificate errors, blocks or CAPTCHAs on those sites | Expected for some sites. Never bypass a CAPTCHA, login, paywall or block. S-3 measures this |
| The PDF download fails with 503 | No renderer configured | `renderer: fpdf2` must be in `deployed.yaml` |
| An entity page fails with 503 | Neo4j is down | The other screens keep working; check `c4c-neo4j` |
| Questions fail with 503 (`llm`) | A model call failed, or the question's budget ran out | Check the provider's status page and the account's credit |

---

## 9. Never do

- Turn on auto-deploy, or deploy on a rehearsal or demo day.
- Put keys, access codes or real city names in the repository.
- Remove `--strict` from the pre-deploy step, or weaken start-up validation to make a deploy pass.
- Open the database or the private services to the internet.
- Enable a search provider's page-content features.
