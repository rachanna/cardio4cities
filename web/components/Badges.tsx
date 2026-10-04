import type { BadgeCard, FactCard } from "@/lib/api";

const BADGE_TONE: Record<string, string> = {
  not_city_level: "warn",
  sources_disagree: "bad",
  outdated: "warn",
  limited_sample: "info",
};

export function Badge({ badge }: { badge: BadgeCard }) {
  return <span className={`chip ${BADGE_TONE[badge.code] ?? ""}`}>{badge.label}</span>;
}

export function StatusChip({ status, word }: { status: string; word: string }) {
  const tone =
    status === "supported" ? "good" : status === "contested" ? "bad" : status === "superseded" ? "info" : "";
  return <span className={`chip ${tone}`}>{word}</span>;
}

export function ConfidenceChip({ card }: { card: FactCard }) {
  if (!card.confidence) return null;
  const tone = card.confidence.label === "high" ? "good" : card.confidence.label === "medium" ? "accent" : "";
  return <span className={`chip ${tone}`}>{card.confidence.label_word}</span>;
}

export function period(card: FactCard): string {
  const { start, end, stated } = card.period;
  if (!stated || (!start && !end)) return "period not stated";
  return start && end && start !== end ? `${start} to ${end}` : (end ?? start ?? "");
}
