# Demo Rehearsal Checklist

Used for both rehearsals and on demo day. The demonstration steps DS-1 to DS-7 come from the brief; pass criteria from `REQUIREMENTS.md` §12.

## 1. Before (one hour ahead)

- [ ] Once, before the first rehearsal: LLD-3 §11.1 (classifier on questions about the past) is closed; prompts and models are frozen from then on
- [ ] Once, before the first rehearsal: spike S-3 run on the deployed service (`python -m scripts.spikes.reachability`, sites listed in the git-ignored `spike_results/s3_sites.txt`); its summary recorded in the BD-36 follow-up row (BD-36)
- [ ] `GET /api/v1/health` returns `ok`, with `checker_independence: different_family`
- [ ] No deploy scheduled; auto-deploy off
- [ ] Fallback city present under "Open existing", with its report downloadable
- [ ] Rehearsal cities purged, except the fallback city
- [ ] Access code and admin code at hand; signed in on the demo laptop; phone ready as a second screen
- [ ] Workflow diagram, run trace and planted-case list open in tabs
- [ ] Prepared questions written down (§3)

## 2. Rehearsal cities

| Rehearsal 1 | Rehearsal 2 |
|---|---|
| A sparse city | A city chosen by someone else, on the spot |
| A non-English city | One of São Paulo, Dakar, Ulaanbaatar |
| An ambiguous name (identity choice appears) | The example-report city |

## 3. Run sheet

| Time | Step | Pass when | If it fails |
|---|---|---|---|
| 0:00 | **DS-1** Ask for the panel's city; confirm identity; start the run | Wave 0 findings appear within about 20 s; progress streams | Continue the deck; return later; fallback city |
| 0:02 | Deck while the run continues | 7 slides in about 10 minutes | Short version: slides 1, 3, 5, 7 |
| ~0:12 | Back to the run | Coverage grid complete; gaps explained; run summary shown | Show what finished; explain the budget stop |
| ~0:15 | **DS-2** Workflow diagram and this run's trace | Diagram generated from code; trace matches | Show the HLD diagrams |
| ~0:20 | **DS-3** Crawl decisions and rejected claims from this run | At least one block or rejection shown with its consequence | Run a planted case from the admin overlay |
| ~0:25 | **DS-4** City brief, explore, entity page | Plain words; badges; confidence reasons | Fallback city |
| ~0:30 | **DS-5** Ask: a figure question, a graph-only question, one with no answer | Cited answers; abstention names the gap; graph switch shows the difference | Prepared questions on the fallback city |
| ~0:35 | **DS-6** Click any fact through to source, passage, dates, geography, verdict, snapshot | Passage highlighted; snapshot opens | Open the snapshot directly |
| ~0:40 | **DS-7** Trade-offs, cuts, limits | From `DECISIONS.md` and slide 7 | — |

## 4. Prepared questions

| Type | Template |
|---|---|
| Figure | "What is the blood pressure control rate in {city}?" |
| Graph-only | "Which organisations run or fund NCD programmes in {city}?" |
| Change over time | "Who runs public health in {city} now, and what did it replace?" |
| No answer expected | "Who is the current head of the city health department?" (when S12 is not answered) |
| Out of scope | "What is the best restaurant in {city}?" |

## 5. After each rehearsal

- [ ] Note every confusing moment, slow step and wrong label
- [ ] Fix, or record as a limit in `DECISIONS.md` §10
- [ ] Re-run the failing step
