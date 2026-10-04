"use client";
// One entity and its one-hop neighbours (HLD §12, owner: a small view, BD-41): drawn in
// code, no graph library. Edge colour says current, ended or contested. Labels sit
// outside each node, on the side away from the centre, so they never cross the lines.
import { useEffect, useState } from "react";
import type { EntityEdge } from "@/lib/api";

const STATUS_COLOUR: Record<string, string> = {
  current: "var(--good)",
  ended: "var(--muted)",
  contested: "var(--bad)",
};

function short(text: string, max = 24): string {
  return text.length > max ? text.slice(0, max - 1) + "…" : text;
}

// A narrow screen gets a smaller canvas, so the text scales up instead of shrinking
const WIDE = { width: 640, height: 420, radius: 150, font: 12, label: 24 };
const NARROW = { width: 380, height: 360, radius: 95, font: 13, label: 12 };

function useNarrow(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    const query = window.matchMedia("(max-width: 600px)");
    const update = () => setNarrow(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return narrow;
}

export function EntityNetwork({
  name,
  edges,
  onPick,
}: {
  name: string;
  edges: EntityEdge[];
  onPick: (entityId: string) => void;
}) {
  const g = useNarrow() ? NARROW : WIDE;
  const cx = g.width / 2;
  const cy = g.height / 2;
  const placed = edges.map((edge, i) => {
    const angle = (2 * Math.PI * i) / Math.max(edges.length, 1) - Math.PI / 2;
    const cos = Math.cos(angle);
    const sin = Math.sin(angle);
    return { edge, x: cx + g.radius * cos, y: cy + g.radius * sin, cos, sin };
  });
  return (
    <figure style={{ margin: 0 }}>
      <svg
        viewBox={`0 0 ${g.width} ${g.height}`}
        width="100%"
        style={{ maxWidth: "40rem", display: "block", margin: "0 auto" }}
        role="img"
        aria-label={`${name} and its ${edges.length} connections`}
      >
        {placed.map(({ edge, x, y }, i) => (
          <line
            key={`l${i}`}
            x1={cx}
            y1={cy}
            x2={x}
            y2={y}
            stroke={STATUS_COLOUR[edge.status] ?? "var(--muted)"}
            strokeWidth={2}
            strokeDasharray={edge.status === "ended" ? "5 4" : undefined}
          />
        ))}
        <circle cx={cx} cy={cy} r={40} fill="var(--accent-soft)" stroke="var(--accent)" />
        <text x={cx} y={cy + 4} textAnchor="middle" fontSize={g.font} fontWeight={700}>
          {short(name, 12)}
        </text>
        {placed.map(({ edge, x, y, cos, sin }, i) => {
          const id = edge.other_entity.entity_id;
          // A label beside the node, away from the centre: left of nodes on the left,
          // right of nodes on the right, above or below near the vertical axis
          const side = Math.abs(cos) < 0.3 ? "middle" : cos > 0 ? "start" : "end";
          const lx = side === "middle" ? x : x + (cos > 0 ? 12 : -12);
          const ly = side === "middle" ? y + (sin > 0 ? 24 : -14) : y + 4;
          return (
            <g
              key={`n${i}`}
              style={{ cursor: id ? "pointer" : "default" }}
              onClick={() => id && onPick(id)}
              role={id ? "link" : undefined}
              aria-label={`${edge.relation} ${edge.other_entity.name}`}
            >
              <circle cx={x} cy={y} r={7} fill="var(--surface)" stroke="var(--text)" strokeWidth={1.5} />
              <text x={lx} y={ly} textAnchor={side} fontSize={g.font}>
                {short(edge.other_entity.name, g.label)}
              </text>
              <text
                x={cx + (x - cx) * 0.55}
                y={cy + (y - cy) * 0.55 - 5}
                textAnchor="middle"
                fontSize="9"
                opacity={0.7}
              >
                {edge.relation.toLowerCase().replace(/_/g, " ")}
              </text>
            </g>
          );
        })}
      </svg>
      <figcaption className="small muted" style={{ textAlign: "center" }}>
        Green: current · grey dashed: ended · red: sources disagree · select a name to open it
      </figcaption>
    </figure>
  );
}
