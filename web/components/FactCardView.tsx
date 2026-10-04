"use client";
import type { FactCard } from "@/lib/api";
import { Badge, ConfidenceChip, StatusChip, period } from "./Badges";
import { useEvidence } from "./Evidence";

/** A fact as every screen shows it (LLD-4 §2.1): the statement, its flags, and a way to
 * its evidence. Wider-area figures always carry their badge (R-08). */
export function FactCardView({ card }: { card: FactCard }) {
  const { open } = useEvidence();
  return (
    <div className="fact">
      <p className="fact-statement">{card.statement}</p>
      <div className="fact-meta">
        {card.main_badge && <Badge badge={card.main_badge} />}
        {card.other_badges.map((b) => (
          <Badge key={b.code} badge={b} />
        ))}
        {card.status !== "supported" && <StatusChip status={card.status} word={card.status_word} />}
        <ConfidenceChip card={card} />
        <span className="muted">
          {card.geography.level_word} · {period(card)} · {card.source.publisher_class}
        </span>
        <button type="button" className="linkish" onClick={() => open(card.claim_id)}>
          Evidence
        </button>
      </div>
    </div>
  );
}
