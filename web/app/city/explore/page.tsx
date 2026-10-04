"use client";
// Explore (HLD §12): every confirmed finding, filtered by dimension, slot, status and
// badge, with both sides of any disagreement together; entities and their connections
// from the knowledge graph.
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import {
  DIMENSIONS,
  get,
  query,
  type BriefResponse,
  type EntitiesResponse,
  type EntityResponse,
  type FindingsResponse,
} from "@/lib/api";
import { CityHeader } from "@/components/CityHeader";
import { CityNav } from "@/components/CityNav";
import { EntityNetwork } from "@/components/EntityNetwork";
import { FactCardView } from "@/components/FactCardView";
import { AccessGate, useApiError } from "@/components/Session";
import { useEvidence } from "@/components/Evidence";

export default function ExplorePage() {
  return (
    <AccessGate>
      <Suspense fallback={<p className="muted">Loading…</p>}>
        <Explore />
      </Suspense>
    </AccessGate>
  );
}

const BADGES = {
  not_city_level: "Not city-level",
  sources_disagree: "Sources disagree",
  outdated: "Outdated",
  limited_sample: "Limited sample",
};

function Explore() {
  const params = useSearchParams();
  const router = useRouter();
  const id = params.get("id") ?? "";
  const entityId = params.get("entity");
  const describe = useApiError();
  const [brief, setBrief] = useState<BriefResponse | null>(null);
  const [filters, setFilters] = useState({ dimension: "", status: "", badge: "" });
  const [findings, setFindings] = useState<FindingsResponse | null>(null);
  const [entities, setEntities] = useState<EntitiesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!id) return;
    get<BriefResponse>(`/cities/${encodeURIComponent(id)}/brief`).then(setBrief).catch((e) => setError(describe(e)));
    get<EntitiesResponse>(`/cities/${encodeURIComponent(id)}/entities`).then(setEntities).catch(() => undefined);
  }, [id, describe]);

  useEffect(() => {
    if (!id) return;
    setFindings(null);
    get<FindingsResponse>(`/cities/${encodeURIComponent(id)}/findings${query({ ...filters, limit: 200 })}`)
      .then(setFindings)
      .catch((e) => setError(describe(e)));
  }, [id, filters, describe]);

  if (!id) return <p className="error">No city was chosen.</p>;
  const pick = (entity: string | null) =>
    router.push(`/city/explore/?id=${encodeURIComponent(id)}${entity ? `&entity=${encodeURIComponent(entity)}` : ""}`);

  return (
    <div className="stack">
      {brief && <CityHeader brief={brief} />}
      <CityNav cityId={id} current="explore" />
      {error && <p className="error">{error}</p>}

      {entityId ? (
        <EntityView cityId={id} entityId={entityId} onPick={pick} />
      ) : (
        <>
          <section className="card row" aria-label="Filters">
            <label className="field" style={{ flex: "1 1 10rem" }}>
              <span className="small muted">Dimension</span>
              <select value={filters.dimension} onChange={(e) => setFilters({ ...filters, dimension: e.target.value })}>
                <option value="">All</option>
                {Object.entries(DIMENSIONS).map(([d, name]) => (
                  <option key={d} value={d}>
                    {d} {name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field" style={{ flex: "1 1 10rem" }}>
              <span className="small muted">Status</span>
              <select value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
                <option value="">All</option>
                <option value="supported">Confirmed</option>
                <option value="contested">Sources disagree</option>
              </select>
            </label>
            <label className="field" style={{ flex: "1 1 10rem" }}>
              <span className="small muted">Flag</span>
              <select value={filters.badge} onChange={(e) => setFilters({ ...filters, badge: e.target.value })}>
                <option value="">Any</option>
                {Object.entries(BADGES).map(([code, label]) => (
                  <option key={code} value={code}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
          </section>

          <h2>Findings</h2>
          {!findings && <p className="muted">Loading…</p>}
          {findings && findings.items.length === 0 && <p className="muted">No finding matches these filters.</p>}
          {findings && (
            <div className="stack">
              {findings.slots
                .filter((s) => findings.items.some((c) => c.slot_id === s.slot_id) || s.gap_note)
                .map((slot) => {
                  const cards = findings.items.filter((c) => c.slot_id === slot.slot_id);
                  return (
                    <section key={slot.slot_id} className="card stack">
                      <div className="spread">
                        <h3 style={{ margin: 0 }}>
                          {slot.slot_id} {slot.question}
                        </h3>
                        <span className="chip">{slot.status_word}</span>
                      </div>
                      {slot.gap_note && <p className="small muted">{slot.gap_note}</p>}
                      {cards.map((card) => (
                        <FactCardView key={card.claim_id} card={card} />
                      ))}
                    </section>
                  );
                })}
            </div>
          )}

          <h2>Organisations, people and programmes</h2>
          {entities && Object.keys(entities.by_type).length === 0 && (
            <p className="muted">No organisation or programme is named by a confirmed fact.</p>
          )}
          {entities &&
            Object.entries(entities.by_type).map(([type, items]) => (
              <section key={type} className="card">
                <h3>{type}</h3>
                <ul className="plain stack">
                  {items.map((e) => (
                    <li key={e.entity_id} className="spread">
                      <button type="button" className="linkish" onClick={() => pick(e.entity_id)}>
                        {e.name}
                      </button>
                      <span className="small muted">
                        {e.facts} {e.facts === 1 ? "fact" : "facts"}
                      </span>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
        </>
      )}
    </div>
  );
}

function EntityView({
  cityId,
  entityId,
  onPick,
}: {
  cityId: string;
  entityId: string;
  onPick: (id: string | null) => void;
}) {
  const describe = useApiError();
  const { open } = useEvidence();
  const [entity, setEntity] = useState<EntityResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setEntity(null);
    setError(null);
    get<EntityResponse>(`/cities/${encodeURIComponent(cityId)}/entities/${encodeURIComponent(entityId)}`)
      .then(setEntity)
      .catch((e) => setError(describe(e)));
  }, [cityId, entityId, describe]);

  return (
    <div className="stack">
      <button type="button" className="linkish" onClick={() => onPick(null)}>
        ← All findings
      </button>
      {error && <p className="error">{error}</p>}
      {!entity && !error && <p className="muted">Loading…</p>}
      {entity && (
        <>
          <h2 style={{ marginTop: 0 }}>
            {entity.entity.name} <span className="chip">{entity.entity.entity_type}</span>
          </h2>
          {entity.edges.length > 0 ? (
            <div className="card">
              <EntityNetwork name={entity.entity.name} edges={entity.edges} onPick={(id) => onPick(id)} />
            </div>
          ) : (
            <p className="muted">No confirmed connection in the knowledge graph.</p>
          )}
          <ul className="plain stack">
            {entity.edges.map((edge, i) => (
              <li key={i} className="card stack">
                <div className="spread">
                  <span>
                    {edge.direction === "outgoing" ? (
                      <>
                        <strong>{entity.entity.name}</strong> {edge.relation.toLowerCase().replace(/_/g, " ")}{" "}
                        <strong>{edge.other_entity.name}</strong>
                      </>
                    ) : (
                      <>
                        <strong>{edge.other_entity.name}</strong> {edge.relation.toLowerCase().replace(/_/g, " ")}{" "}
                        <strong>{entity.entity.name}</strong>
                      </>
                    )}
                  </span>
                  <span className={`chip ${edge.status === "contested" ? "bad" : edge.status === "ended" ? "" : "good"}`}>
                    {edge.status === "current" ? "Current" : edge.status === "ended" ? "Ended" : "Sources disagree"}
                  </span>
                </div>
                <span className="small muted">
                  {edge.valid_from ? `from ${edge.valid_from}` : "start not stated"}
                  {edge.valid_to ? ` to ${edge.valid_to}` : ""}
                </span>
                <span className="row small">
                  {edge.claim_ids.map((claim) => (
                    <button key={claim} type="button" className="linkish" onClick={() => open(claim)}>
                      Evidence
                    </button>
                  ))}
                </span>
              </li>
            ))}
          </ul>
          <p className="small muted">Read from the knowledge graph; every connection is checked again against the confirmed facts.</p>
        </>
      )}
    </div>
  );
}
