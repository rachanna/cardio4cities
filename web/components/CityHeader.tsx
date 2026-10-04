import { formatDate, type BriefResponse } from "@/lib/api";

export function CityHeader({ brief }: { brief: BriefResponse }) {
  const city = brief.city as Record<string, string | null>;
  return (
    <header style={{ marginTop: "1.5rem" }}>
      <h1>{String(city.name)}</h1>
      <p className="muted small">
        {[city.admin1_name, city.country_name].filter(Boolean).join(", ")} · researched{" "}
        {formatDate(brief.run.finished_at ?? brief.run.started_at)}
        {brief.run.status !== "completed" ? " · stopped at its limit" : ""}
      </p>
    </header>
  );
}
