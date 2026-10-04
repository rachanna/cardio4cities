"use client";
// The evidence panel (HLD §12, AT-12): from any fact to its source, the exact passage,
// dates, geography, verdict, every flag and the preserved snapshot.
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { API, formatDate, get, type EvidenceResponse } from "@/lib/api";
import { Badge, ConfidenceChip, StatusChip, period } from "./Badges";

const Ctx = createContext<{ open: (claimId: string) => void } | null>(null);

export function useEvidence() {
  const value = useContext(Ctx);
  if (!value) throw new Error("useEvidence outside EvidenceProvider");
  return value;
}

export function EvidenceProvider({ children }: { children: ReactNode }) {
  const [claimId, setClaimId] = useState<string | null>(null);
  const open = useCallback((id: string) => setClaimId(id), []);
  const close = useCallback(() => setClaimId(null), []);
  return (
    <Ctx.Provider value={{ open }}>
      {children}
      {claimId && <EvidencePanel claimId={claimId} onClose={close} />}
    </Ctx.Provider>
  );
}

function EvidencePanel({ claimId, onClose }: { claimId: string; onClose: () => void }) {
  const [data, setData] = useState<EvidenceResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    get<EvidenceResponse>(`/facts/${encodeURIComponent(claimId)}/evidence`)
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, [claimId]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div className="drawer-backdrop" onClick={onClose} />
      <aside className="drawer stack" role="dialog" aria-modal="true" aria-label="Evidence">
        <div className="spread">
          <h2 style={{ margin: 0 }}>Evidence</h2>
          <button className="button quiet" type="button" onClick={onClose}>
            Close
          </button>
        </div>
        {error && <p className="error">{error}</p>}
        {!data && !error && <p className="muted">Loading…</p>}
        {data && <EvidenceBody data={data} />}
      </aside>
    </>
  );
}

function Passage({ data }: { data: EvidenceResponse }) {
  const p = data.passage;
  if (!p) return <p className="muted">The passage is not stored for this source.</p>;
  return (
    <div className="passage">
      {p.text.slice(0, p.highlight_start)}
      <mark>{p.text.slice(p.highlight_start, p.highlight_end)}</mark>
      {p.text.slice(p.highlight_end)}
    </div>
  );
}

function population(data: EvidenceResponse): string {
  const pop = data.card.population;
  const ages =
    pop.age_min != null || pop.age_max != null
      ? `aged ${pop.age_min ?? "?"}${pop.age_max != null ? `-${pop.age_max}` : " and over"}`
      : null;
  const sex = pop.sex !== "not_stated" && pop.sex !== "all" ? pop.sex : null;
  return [pop.group, ages, sex].filter(Boolean).join(", ") || "not stated";
}

function EvidenceBody({ data }: { data: EvidenceResponse }) {
  const card = data.card;
  const distance = data.geography_fit?.["distance_km"];
  return (
    <>
      <p style={{ fontWeight: 600 }}>{card.statement}</p>
      <div className="fact-meta">
        <StatusChip status={card.status} word={card.status_word} />
        {card.main_badge && <Badge badge={card.main_badge} />}
        {card.other_badges.map((b) => (
          <Badge key={b.code} badge={b} />
        ))}
        <ConfidenceChip card={card} />
      </div>

      <h3>Passage from the source</h3>
      <Passage data={data} />
      {data.quote_translation && <p className="small muted">Translation: {data.quote_translation}</p>}
      {Object.entries(data.label_passages).map(([kind, text]) => (
        <p key={kind} className="small">
          <span className="muted">Where the {kind} is stated:</span> “{text}”
        </p>
      ))}

      <h3>Source</h3>
      <dl className="facts small">
        <dt>Title</dt>
        <dd>{card.source.title ?? "Untitled"}</dd>
        <dt>Publisher</dt>
        <dd>{card.source.publisher_class}</dd>
        <dt>Link</dt>
        <dd>
          <a href={card.source.url} target="_blank" rel="noreferrer noopener">
            {card.source.url}
          </a>
        </dd>
        <dt>Published</dt>
        <dd>{card.source.published_date ?? "not stated"}</dd>
        <dt>Retrieved</dt>
        <dd>{formatDate(card.source.retrieved_at)}</dd>
        <dt>Snapshot</dt>
        <dd>
          {data.snapshot ? (
            <a
              href={`${API}/snapshots/${encodeURIComponent(card.source.source_id)}`}
              target="_blank"
              rel="noreferrer"
            >
              Open the page as retrieved
            </a>
          ) : (
            "not stored"
          )}
        </dd>
      </dl>

      <h3>What it describes</h3>
      <dl className="facts small">
        <dt>Area</dt>
        <dd>
          {card.geography.name} ({card.geography.level_word})
          {typeof distance === "number" && distance > 0 ? `, ${distance} km from the city` : ""}
        </dd>
        <dt>Period</dt>
        <dd>{period(card)}</dd>
        <dt>Population</dt>
        <dd>{population(data)}</dd>
      </dl>

      <h3>Independent check</h3>
      {data.verdict ? (
        <dl className="facts small">
          <dt>Verdict</dt>
          <dd>{data.verdict.label}</dd>
          <dt>Why</dt>
          <dd>{data.verdict.rationale}</dd>
          <dt>Checked by</dt>
          <dd>
            {data.verdict.model}
            {data.verdict.fallback_used ? " (fallback checker)" : ""}
          </dd>
        </dl>
      ) : (
        <p className="muted small">Not checked.</p>
      )}
      {data.consistency && (
        <p className="small">
          <span className="muted">Compared with other figures:</span> {data.consistency.outcome}.{" "}
          {data.consistency.reason}
        </p>
      )}
      {card.confidence && (
        <>
          <h3>Why this confidence</h3>
          <ul className="small">
            {card.confidence.reasons.map((r) => (
              <li key={r.component}>
                {r.note} ({r.points} {r.points === 1 ? "point" : "points"})
              </li>
            ))}
          </ul>
          {card.confidence.capped_by && (
            <p className="small muted">Held at Medium: {card.confidence.capped_by}.</p>
          )}
        </>
      )}
    </>
  );
}
