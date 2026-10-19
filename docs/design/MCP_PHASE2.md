# MCP server, phase 2: collection behind the server (design note, E-16)

Status: **proposal for owner review**. Phase 1 (BD-60) moved search and prompts. This note
covers the rest of the agent's tools: the crawl gate, fetching, parsing and the official
structured-data APIs. Nothing here is built yet.

## 1. What moves and what stays

| Moves to the server | Stays in the agent |
|---|---|
| The crawl gate (address checks, robots.txt, usage preferences, every redirect hop) | Persisting sources, gate decisions, snapshots and events (Postgres) |
| Fetching with pinned addresses, TLS chain completion, per-domain spacing | The budget ledger and the run's wall clock |
| Parsing HTML, PDF and text into documents and table spans | The parser, for `poe reindex` and for code verification of stored snapshots |
| Official API requests for structured data (WHO GHO, World Bank) | Parsing structured-data responses into records (verification re-parses the snapshot) |
| | All three stores, every model call, the checker |

The agent decides *what* to read; the server is the only part of the system that touches
the web. That is a security gain in its own right: the agent process then needs no web
access except to its model providers, and every egress control (address checks, pinning,
redirect limits, size caps) sits in one place, which is what MCP's security guidance
recommends for server-side requests.

## 2. Invariants that must survive the move

1. **The gate decides before any content request** (non-negotiable 3), and its decision is
   a step in the workflow graph (non-negotiable 2): the `crawl_gate` node keeps calling a
   gate, now a tool.
2. **Every redirect hop is gated again**, and every request dials the address the gate
   checked.
3. **Every request reserves budget first** (CLAUDE.md), including robots.txt and
   certificate fetches, and none starts after the run is stopped (BD-27).
4. **The bytes parsed are the bytes stored**, and code verification re-parses the snapshot
   with the same parser (R-56, BD-56).
5. **Fetched text is untrusted**: it is never logged, and only the agent's prompt builders
   put it in front of a model, escaped by `safety.py`.
6. **Events are written before they are streamed**: decisions are persisted by the agent,
   as today.

## 3. The seam

`app/workflow/collection.py` already has the right boundary: `Collector.gate(url)`,
`Collector.collect(url, keywords)` and `Collector.fetch_api(url, provider)` return
decisions, bytes and documents, and the workflow node persists them. Phase 2 moves the
`Collector` into the server unchanged and gives the agent a port in its place.

- `app/ports/collect.py`: `CollectorPort` with `gate`, `collect`, `fetch_api`, and the result
  types (`GateDecision`, `Collected`, `ApiFetched`) moved out of the workflow.
- In-process implementation: today's `Collector` (tests, `TOOLS_VIA_MCP=0`).
- `app/adapters/mcp/collect.py`: `RemoteCollector`, the same port over three tools:

| Tool | Hints | Returns |
|---|---|---|
| `crawl_gate(collection, url)` | read-only towards the agent; open-world (it may fetch robots.txt) | one decision: outcome, reason, rule, pinned address, crawl delay, usage preferences |
| `collect_page(collection, url, table_keywords, allowance, deadline_s)` | open-world | a decision per hop, outcome, status, content type, kind, document, parse outcome, raw bytes (base64) with their SHA-256, requests used |
| `fetch_api(collection, url, provider, allowance, deadline_s)` | open-world | a decision per hop, the 2xx body (base64) with its SHA-256, requests used |

## 4. The four hard problems

### 4.1 Per-run state: a collection handle

The collector keeps state for a run: robots.txt per origin, completed certificate chains,
per-domain spacing. Under the stateless 2026-07-28 protocol, state lives behind a
server-minted handle passed as an argument.

**Proposal:** `open_collection()` returns a random, expiring handle bound to the caller's
token; each holds one `Collector`. The runner opens one per run and closes it at the end.
The MCP spec's rule applies: a handle is never authentication, and another caller's handle
is refused.

*Alternative:* one server-wide cache with a TTL. Simpler, and politeness spacing becomes
global across callers, which is more honest to sites. But today's per-run robots read
changes, and so does the budget count of robots fetches. Not recommended for phase 2.

### 4.2 Budget: hold and settle

Today the collector reserves each request (`fetch`, `robots`, `certificate`) from the
run's ledger just before making it. A server cannot call back into the agent's ledger in
the middle of a tool call (the 2026-07-28 protocol deprecated server-to-client requests).

**Proposal:** before each `collect_page` or `fetch_api` call, the agent **holds** a per-call
allowance from the ledger (for example 1 page fetch + up to 5 redirect hops (`MAX_REDIRECTS`, LLD-2 §9.3) + 1
robots.txt + 2 certificate fetches [tunable]). The server never exceeds the allowance and
returns what it used, and the ledger **settles**: unused requests go back. "Reserve before
every request" still holds, at the granularity of the allowance. This needs `hold` and
`settle` on `BudgetLedger`, a change to BD-15's accounting recorded in a new BD row.

*Rejected:* counting after the call. It would let the server make requests the run never
reserved.

### 4.3 Time and cancellation

Each call carries `deadline_s` (the run's time left); the server applies it as the
collector's total timeout. When the run's task is cancelled, the MCP client sends
`notifications/cancelled`, and the server cancels the request's task and every request
under it. A test proves a stopped run stops its server-side requests (BD-27).

### 4.4 Bytes and parsing

The raw bytes travel as base64 in the structured result with their SHA-256; the agent
checks the hash and stores the snapshot itself, so the stored bytes are the bytes the
server parsed. Bodies are capped at `fetch.max_bytes` (10 MB, about 13 MB as base64:
fine on loopback).

The server parses, and the agent still needs the same parser for `poe reindex` and
verification. **Proposal:** a parser version, a hash of the parser adapter and
`parse_body`, served by the server and checked at start-up exactly as prompt versions are
(BD-60). On a mismatch the agent refuses to start.

## 5. Outside MCP clients

A gated fetcher open to other agents is a crawler running under our user agent from this
machine. **Proposal:** each `mcp.clients` entry gets a tool allow-list; outside clients keep
`search_links` and the prompts, and the collection tools are agent-only until the owner
opens them, with their own fetch quota. Any page text returned to an outside client is
marked in the result as untrusted web content.

## 6. Tests

- The collection acceptance tests (AT-04, AT-05, AT-06, AT-23) run against **both** the
  in-process collector and `RemoteCollector` over the MCP protocol in-process, as the
  search contract does (AT-35).
- Hold and settle: an allowance is never exceeded; unused requests return; an exhausted
  ledger refuses before any call.
- Cancellation: a cancelled run leaves no server-side request running.
- Byte identity: the stored snapshot's hash equals the server's; a mismatch is refused.
- A handle presented by another caller is refused; an expired handle is refused.
- A parser version mismatch refuses start-up.

## 7. Plan

1. Move the result types into `app/ports/collect.py`, behind `CollectorPort` (no behaviour change).
2. Add `hold` and `settle` to the ledger; the in-process collector uses them too.
3. Server: `open_collection`, `crawl_gate`, `collect_page`, `fetch_api`, the per-client tool allow-list.
4. `RemoteCollector`, the parser version check, cancellation.
5. Run the acceptance tests over both implementations; a live run on the free profile.
6. BD rows, LLD-2 §9 and LLD-4 §8 updates.

About 2.5 to 3 days.

## 8. Decisions for the owner

1. **Per-run state:** collection handles (recommended), or a server-wide cache with a TTL?
2. **Budget:** add hold-and-settle to the ledger (recommended)?
3. **Parsing:** on the server, with a parser version check (recommended), or kept in the
   agent (the server returns bytes only)?
4. **Outside clients:** collection tools agent-only for now (recommended), or open them
   with a fetch quota?
