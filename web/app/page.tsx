"use client";
// Start (HLD §12): find the city, see exactly which place was chosen before research
// starts (AT-24), then follow the live run; or open a city researched earlier (AT-25).
import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ApiError,
  formatDate,
  get,
  post,
  type CityItem,
  type PlaceCandidate,
  type ResolveResponse,
  type SlotInfo,
  type StartRunResponse,
} from "@/lib/api";
import { RunProgress } from "@/components/RunProgress";
import { AccessGate, useApiError } from "@/components/Session";

export default function StartPage() {
  return (
    <AccessGate>
      <Start />
    </AccessGate>
  );
}

function placeLine(p: PlaceCandidate): string {
  const where = [p.admin1_name, p.country_name].filter(Boolean).join(", ");
  const people = p.population ? ` · population ${p.population.toLocaleString()}` : "";
  return `${where}${people}`;
}

function Start() {
  const describe = useApiError();
  const [queryText, setQueryText] = useState("");
  const [candidates, setCandidates] = useState<PlaceCandidate[] | null>(null);
  const [chosen, setChosen] = useState<PlaceCandidate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [run, setRun] = useState<{ runId: string; cityId: string } | null>(null);
  const [slots, setSlots] = useState<SlotInfo[]>([]);
  const [cities, setCities] = useState<CityItem[] | null>(null);

  useEffect(() => {
    get<SlotInfo[]>("/slots").then(setSlots).catch(() => undefined);
    get<{ items: CityItem[] }>("/cities")
      .then((r) => setCities(r.items))
      .catch((e) => setError(describe(e)));
  }, [describe]);

  async function search(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setChosen(null);
    try {
      const result = await post<ResolveResponse>("/cities/resolve", { query: queryText.trim() });
      setCandidates(result.candidates);
      if (result.exact && result.candidates[0]) setChosen(result.candidates[0]);
      if (!result.candidates.length) setError("No place by that name is in the gazetteer. Check the spelling.");
    } catch (e) {
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  async function research() {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const started = await post<StartRunResponse>("/runs", { gazetteer_id: chosen.gazetteer_id });
      setRun({ runId: started.run_id, cityId: started.city_id });
    } catch (e) {
      if (e instanceof ApiError && e.code === "run_in_progress" && typeof e.details.run_id === "string") {
        const other = await get<{ city_id: string }>(`/runs/${e.details.run_id}`).catch(() => null);
        if (other) {
          setError("Another city is being researched. You are now watching that run.");
          setRun({ runId: e.details.run_id, cityId: other.city_id });
          return;
        }
      }
      setError(describe(e));
    } finally {
      setBusy(false);
    }
  }

  if (run) {
    return (
      <div className="stack">
        <h1 style={{ marginTop: "1.5rem" }}>{chosen ? chosen.name : "Research in progress"}</h1>
        {chosen && <p className="muted">{placeLine(chosen)}</p>}
        {error && <p className="notice">{error}</p>}
        <RunProgress runId={run.runId} cityId={run.cityId} slots={slots} />
      </div>
    );
  }

  return (
    <div className="stack">
      <section className="card stack" style={{ marginTop: "1.5rem" }}>
        <h1>Research a city</h1>
        <p className="muted">
          The system searches the public web now, checks every claim against its source, and builds a cited
          brief. A run takes a few minutes.
        </p>
        <form className="row" onSubmit={search}>
          <label className="field" style={{ flex: "1 1 16rem" }}>
            <span className="small muted">City name</span>
            <input
              value={queryText}
              onChange={(e) => setQueryText(e.target.value)}
              placeholder="For example, Halden Bay"
              aria-label="City name"
              required
            />
          </label>
          <button className="button" type="submit" disabled={busy || !queryText.trim()} style={{ alignSelf: "flex-end" }}>
            Find
          </button>
        </form>

        {candidates && candidates.length > 0 && (
          <div className="stack">
            <p className="small muted">
              {candidates.length > 1 ? "Several places match. Choose the one you mean:" : "One place matches:"}
            </p>
            <ul className="plain stack">
              {candidates.map((c) => (
                <li key={c.gazetteer_id}>
                  <label className="row" style={{ cursor: "pointer" }}>
                    <input
                      type="radio"
                      name="place"
                      checked={chosen?.gazetteer_id === c.gazetteer_id}
                      onChange={() => setChosen(c)}
                    />
                    <span>
                      <strong>{c.name}</strong> <span className="muted small">{placeLine(c)}</span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </div>
        )}

        {chosen && (
          <div className="notice stack">
            <p style={{ margin: 0 }}>
              You chose <strong>{chosen.name}</strong>, {placeLine(chosen)}. Research starts fresh and live.
            </p>
            <button className="button" type="button" onClick={() => void research()} disabled={busy}>
              {busy ? "Starting…" : `Research ${chosen.name}`}
            </button>
          </div>
        )}
        {error && <p className="error" role="alert">{error}</p>}
      </section>

      <section className="card stack">
        <h2 style={{ marginTop: 0 }}>Open existing</h2>
        {cities === null && !error && <p className="muted">Loading…</p>}
        {cities && cities.length === 0 && <p className="muted">No city has been researched yet.</p>}
        {cities && cities.length > 0 && (
          <ul className="plain stack">
            {cities.map((c) => (
              <li key={c.city_id} className="spread">
                <span>
                  <Link href={`/city/?id=${encodeURIComponent(c.city_id)}`}>
                    <strong>{c.name}</strong>
                  </Link>{" "}
                  <span className="muted small">{c.country_name}</span>
                </span>
                <span className="small muted">
                  Researched {formatDate(c.latest_run_at)}
                  {c.latest_run_status !== "completed" ? " (stopped at its limit)" : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
