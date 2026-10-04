"use client";
// City brief (HLD §12): the stored research of the city's latest run (AT-25): headline
// facts per dimension (High and Medium confidence only, HD-08), the coverage grid, what to
// handle with care, and the report download.
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { API, DIMENSIONS, get, type BriefResponse } from "@/lib/api";
import { CityHeader } from "@/components/CityHeader";
import { CityNav } from "@/components/CityNav";
import { CoverageGrid, cellsFromRows } from "@/components/CoverageGrid";
import { FactCardView } from "@/components/FactCardView";
import { AccessGate, useApiError } from "@/components/Session";

export default function BriefPage() {
  return (
    <AccessGate>
      <Suspense fallback={<p className="muted">Loading…</p>}>
        <Brief />
      </Suspense>
    </AccessGate>
  );
}

function Brief() {
  const id = useSearchParams().get("id") ?? "";
  const describe = useApiError();
  const [brief, setBrief] = useState<BriefResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    get<BriefResponse>(`/cities/${encodeURIComponent(id)}/brief`)
      .then(setBrief)
      .catch((e) => setError(describe(e)));
  }, [id, describe]);

  if (!id) return <p className="error">No city was chosen.</p>;
  if (error) return <p className="error" style={{ marginTop: "1.5rem" }}>{error}</p>;
  if (!brief) return <p className="muted">Loading…</p>;

  const report = (format: string) => `${API}/cities/${encodeURIComponent(id)}/report?format=${format}`;
  const counts = brief.counts as { claims?: Record<string, number>; sources?: { read?: number } };

  return (
    <div className="stack">
      <CityHeader brief={brief} />
      <CityNav cityId={id} current="brief" />

      <div className="card spread">
        <span className="small muted">
          {counts.claims && counts.sources
            ? `${counts.claims.supported ?? 0} confirmed claims from ${counts.sources.read ?? 0} sources read`
            : "Download the full report with every source."}
        </span>
        <span className="row">
          <a className="button" href={report("pdf")}>
            Download report (PDF)
          </a>
          <a className="button secondary" href={report("html")}>
            HTML
          </a>
          <a className="button secondary" href={report("md")}>
            Markdown
          </a>
        </span>
      </div>

      <h2>Summary</h2>
      {Object.keys(brief.summary).length === 0 && (
        <p className="muted">No fact reached High or Medium confidence. See the coverage below.</p>
      )}
      {Object.entries(brief.summary).map(([dimension, cards]) => (
        <section key={dimension} className="card stack">
          <h3 style={{ margin: 0 }}>{DIMENSIONS[dimension] ?? dimension}</h3>
          {cards.map((card) => (
            <FactCardView key={card.claim_id} card={card} />
          ))}
        </section>
      ))}

      {brief.handle_with_care.length > 0 && (
        <>
          <h2>Handle with care</h2>
          {brief.handle_with_care.map((item) => (
            <div key={item.card.claim_id} className="card stack">
              <p className="small" style={{ margin: 0, color: "var(--warn)", fontWeight: 600 }}>
                {item.reason}
              </p>
              <FactCardView card={item.card} />
            </div>
          ))}
        </>
      )}

      <h2>Coverage</h2>
      <p className="small muted">Every question the research asks, with what was found or why not.</p>
      <CoverageGrid cells={cellsFromRows(brief.coverage)} />
    </div>
  );
}
