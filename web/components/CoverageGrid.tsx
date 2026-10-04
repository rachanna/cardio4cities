import type { SlotInfo, SlotRow } from "@/lib/api";
import { DIMENSIONS } from "@/lib/api";

export interface GridCell {
  slot_id: string;
  question: string;
  dimension: string;
  status?: string; // absent while the slot is still being researched
  status_word?: string;
  gap_note?: string | null;
  headline?: boolean;
}

const WORDS: Record<string, string> = {
  answered: "Answered",
  answered_wider_geo: "Wider area only",
  answered_negative: "Not found",
  blocked: "Blocked by source",
  unreachable: "Source unreachable",
};

export function cellsFromRows(rows: SlotRow[]): GridCell[] {
  return rows.map((r) => ({ ...r, status_word: r.status_word }));
}

export function cellsFromSlots(slots: SlotInfo[], statuses: Record<string, { status: string; gap_note?: string | null }>): GridCell[] {
  return slots.map((s) => {
    const got = statuses[s.slot_id];
    return {
      slot_id: s.slot_id,
      question: s.question,
      dimension: s.dimension,
      headline: s.headline,
      status: got?.status,
      status_word: got ? (WORDS[got.status] ?? got.status) : undefined,
      gap_note: got?.gap_note,
    };
  });
}

/** The coverage grid (AT-32): every slot with its status, grouped by dimension. */
export function CoverageGrid({ cells }: { cells: GridCell[] }) {
  const dimensions = Object.keys(DIMENSIONS).filter((d) => cells.some((c) => c.dimension === d));
  return (
    <div className="stack">
      {dimensions.map((d) => (
        <section key={d}>
          <h3 className="small muted" style={{ marginBottom: "0.35rem" }}>
            {d} {DIMENSIONS[d]}
          </h3>
          <div className="grid">
            {cells
              .filter((c) => c.dimension === d)
              .map((c) => (
                <div key={c.slot_id} className={`slot ${c.status ?? "pending"}`}>
                  <div className="small">
                    <span className="id">{c.slot_id}</span>
                    {c.headline && <span className="chip accent">Headline</span>}
                  </div>
                  <div className="small">{c.question}</div>
                  <div className="small" style={{ marginTop: "0.25rem", fontWeight: 600 }}>
                    {c.status_word ?? "Researching…"}
                  </div>
                  {c.gap_note && <div className="small muted">{c.gap_note}</div>}
                </div>
              ))}
          </div>
        </section>
      ))}
    </div>
  );
}
