"use client";
// Live progress (LLD-4 §4, AT-30): built from the event stream alone. The browser resumes
// with Last-Event-ID after a drop; the server replays from Postgres, so nothing is lost.
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { API, type SlotInfo } from "@/lib/api";
import { CoverageGrid, cellsFromSlots } from "./CoverageGrid";

const TYPES = [
  "run_started", "wave0_finding", "slot_planned", "search_done", "crawl_decision",
  "source_fetched", "source_unreadable", "claim_extracted", "claim_dropped", "claim_verdict",
  "conflict_found", "fact_written", "slot_status", "budget_warning", "step_failed", "run_finished",
] as const;

interface Wave0 {
  indicator_code: string;
  value_as_written: string;
  geography_level: string;
  provider: string;
  status?: string;
}

interface Progress {
  searches: number;
  read: number;
  blocked: number;
  unreachable: number;
  confirmed: number;
  rejected: number;
  log: string[];
  wave0: Wave0[];
  slots: Record<string, { status: string; gap_note?: string | null }>;
  finished: { status: string } | null;
  warnings: string[];
}

const EMPTY: Progress = {
  searches: 0, read: 0, blocked: 0, unreachable: 0, confirmed: 0, rejected: 0,
  log: [], wave0: [], slots: {}, finished: null, warnings: [],
};

const OUTCOME: Record<string, string> = {
  allowed: "allowed",
  blocked_robots: "blocked by robots.txt",
  blocked_content_usage: "content opted out of AI use",
  blocked_login_or_paywall: "login or paywall",
  blocked_private_address: "private address refused",
  unreachable_network: "unreachable",
  unreachable_server_error: "server error",
  rate_limited: "rate limited",
};

function apply(p: Progress, type: string, data: Record<string, any>): Progress {
  const log = (line: string) => [line, ...p.log].slice(0, 40);
  switch (type) {
    case "search_done":
      return { ...p, searches: p.searches + 1 };
    case "crawl_decision": {
      const blocked = String(data.outcome).startsWith("blocked");
      const unreachable = String(data.outcome).startsWith("unreachable") || data.outcome === "rate_limited";
      return {
        ...p,
        blocked: p.blocked + (blocked ? 1 : 0),
        unreachable: p.unreachable + (unreachable ? 1 : 0),
        log: data.outcome === "allowed" ? p.log : log(`${data.domain}: ${OUTCOME[data.outcome] ?? data.outcome}`),
      };
    }
    case "source_fetched":
      return { ...p, read: p.read + 1, log: log(`Read ${new URL(data.url).hostname}`) };
    case "claim_verdict":
      return data.label === "supported"
        ? { ...p, confirmed: p.confirmed + 1 }
        : { ...p, rejected: p.rejected + 1 };
    case "wave0_finding":
      return { ...p, wave0: [...p.wave0, data as Wave0] };
    case "slot_status":
      return { ...p, slots: { ...p.slots, [data.slot_id]: { status: data.status, gap_note: data.gap_note } } };
    case "budget_warning":
      return { ...p, warnings: [...p.warnings, `${data.counter} at ${data.used} of ${data.limit}`] };
    case "run_finished":
      return { ...p, finished: { status: data.status } };
    default:
      return p;
  }
}

const FINISHED_WORDS: Record<string, string> = {
  completed: "Research complete.",
  stopped_by_budget: "Research stopped at its time or spending limit; results so far are kept.",
  failed: "The run failed. What was found before the failure is kept.",
};

export function RunProgress({ runId, cityId, slots }: { runId: string; cityId: string; slots: SlotInfo[] }) {
  const [p, setP] = useState<Progress>(EMPTY);
  const [connected, setConnected] = useState(true);

  useEffect(() => {
    const source = new EventSource(`${API}/runs/${encodeURIComponent(runId)}/events`);
    const handlers = TYPES.map((type) => {
      const handler = (e: MessageEvent) => {
        setConnected(true);
        let data: Record<string, any> = {};
        try {
          data = JSON.parse(e.data);
        } catch {
          return;
        }
        setP((prev) => apply(prev, type, data));
        if (type === "run_finished") source.close();
      };
      source.addEventListener(type, handler as EventListener);
      return [type, handler] as const;
    });
    source.onerror = () => setConnected(false); // the browser retries with Last-Event-ID
    return () => {
      handlers.forEach(([type, h]) => source.removeEventListener(type, h as EventListener));
      source.close();
    };
  }, [runId]);

  const cells = useMemo(() => cellsFromSlots(slots, p.slots), [slots, p.slots]);
  const done = Object.keys(p.slots).length;

  return (
    <section className="stack" aria-live="polite">
      <div className="card stack">
        <div className="spread">
          <strong>{p.finished ? FINISHED_WORDS[p.finished.status] ?? "Finished." : "Researching live…"}</strong>
          {!connected && !p.finished && <span className="chip warn">Reconnecting…</span>}
        </div>
        <div className="row small">
          <span className="chip">{p.searches} searches</span>
          <span className="chip">{p.read} sources read</span>
          <span className="chip">{p.blocked} blocked</span>
          <span className="chip">{p.unreachable} unreachable</span>
          <span className="chip good">{p.confirmed} claims confirmed</span>
          <span className="chip">{p.rejected} not confirmed</span>
          <span className="chip accent">
            {done} of {slots.length} questions settled
          </span>
        </div>
        {p.finished && (
          <Link className="button" href={`/city/?id=${encodeURIComponent(cityId)}`}>
            Open the city brief
          </Link>
        )}
      </div>

      {p.wave0.length > 0 && (
        <div className="card">
          <h3>Official data first (Wave 0)</h3>
          <ul className="plain small">
            {p.wave0.map((w, i) => (
              <li key={i}>
                {w.indicator_code}: <strong>{w.value_as_written || "no value"}</strong>{" "}
                <span className="muted">
                  ({w.geography_level}, {w.provider}
                  {w.status ? `, ${w.status}` : ""})
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <CoverageGrid cells={cells} />

      {p.log.length > 0 && (
        <div className="card">
          <h3>What the crawler did</h3>
          <ul className="plain log">
            {p.log.map((line, i) => (
              <li key={i}>{line}</li>
            ))}
          </ul>
        </div>
      )}
      {p.warnings.length > 0 && <p className="notice small">Budget: {p.warnings.join("; ")}</p>}
    </section>
  );
}
