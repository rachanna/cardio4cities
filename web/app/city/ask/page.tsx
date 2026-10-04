"use client";
// Ask (HLD §12, LLD-5): questions answered only from confirmed facts, each sentence cited
// and badged; gaps answered honestly. Follow-ups keep the conversation. The presenter can
// switch the knowledge graph off (R-88) and see why an answer came out as it did.
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { get, post, type AnswerSentence, type AskResponse, type BriefResponse } from "@/lib/api";
import { Badge } from "@/components/Badges";
import { CityHeader } from "@/components/CityHeader";
import { CityNav } from "@/components/CityNav";
import { useEvidence } from "@/components/Evidence";
import { AccessGate, useApiError, useSession } from "@/components/Session";

export default function AskPage() {
  return (
    <AccessGate>
      <Suspense fallback={<p className="muted">Loading…</p>}>
        <Ask />
      </Suspense>
    </AccessGate>
  );
}

interface Turn {
  question: string;
  answer: AskResponse | null;
  error?: string;
  graphOff: boolean;
}

function Ask() {
  const id = useSearchParams().get("id") ?? "";
  const describe = useApiError();
  const { isAdmin } = useSession();
  const [brief, setBrief] = useState<BriefResponse | null>(null);
  const [text, setText] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [conversation, setConversation] = useState<string | null>(null);
  const [graphOff, setGraphOff] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (id) get<BriefResponse>(`/cities/${encodeURIComponent(id)}/brief`).then(setBrief).catch(() => undefined);
  }, [id]);

  async function ask(event: React.FormEvent) {
    event.preventDefault();
    const question = text.trim();
    if (!question) return;
    setBusy(true);
    setText("");
    const turn: Turn = { question, answer: null, graphOff };
    setTurns((t) => [...t, turn]);
    try {
      const answer = await post<AskResponse>(`/cities/${encodeURIComponent(id)}/ask`, {
        question,
        conversation_id: conversation,
        options: { graph: graphOff ? "off" : "on" },
      });
      setConversation(answer.conversation_id);
      setTurns((t) => t.map((x) => (x === turn ? { ...x, answer } : x)));
    } catch (e) {
      const message = describe(e);
      setTurns((t) => t.map((x) => (x === turn ? { ...x, error: message } : x)));
    } finally {
      setBusy(false);
    }
  }

  if (!id) return <p className="error">No city was chosen.</p>;

  return (
    <div className="stack">
      {brief && <CityHeader brief={brief} />}
      <CityNav cityId={id} current="ask" />
      <p className="small muted">
        Answers use only facts confirmed for this city, each with its source. Where nothing was confirmed, the answer
        says so.
      </p>

      <div className="stack">
        {turns.map((turn, i) => (
          <div key={i} className="stack">
            <div className="bubble-q">
              {turn.question}
              {turn.graphOff && <span className="chip warn" style={{ marginLeft: "0.5rem" }}>graph off</span>}
            </div>
            <div className="card">
              {turn.error && <p className="error">{turn.error}</p>}
              {!turn.answer && !turn.error && <p className="muted">Checking the evidence…</p>}
              {turn.answer && <Answer answer={turn.answer} />}
            </div>
          </div>
        ))}
      </div>

      <form className="card stack" onSubmit={ask}>
        <label className="field">
          <span className="small muted">{conversation ? "Ask a follow-up" : "Your question"}</span>
          <input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="For example, who runs public health in the city?"
            maxLength={500}
            aria-label="Question"
          />
        </label>
        <div className="spread">
          {isAdmin ? (
            <label className="row small">
              <input type="checkbox" checked={graphOff} onChange={(e) => setGraphOff(e.target.checked)} />
              Switch the knowledge graph off (demonstration)
            </label>
          ) : (
            <span />
          )}
          <div className="row">
            {conversation && (
              <button
                type="button"
                className="button quiet"
                onClick={() => {
                  setConversation(null);
                  setTurns([]);
                }}
              >
                New conversation
              </button>
            )}
            <button className="button" type="submit" disabled={busy || !text.trim()}>
              Ask
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

function Sentence({ s }: { s: AnswerSentence }) {
  const { open } = useEvidence();
  const facts = s.refs.filter((r) => r.startsWith("clm_"));
  return (
    <p className={`sentence sentence-${s.kind}`}>
      {s.kind === "analysis" && <strong>Analysis: </strong>}
      {s.kind === "mention" && <span className="chip warn">Reported, not confirmed</span>} {s.text}
      {facts.map((claim, i) => (
        <button key={claim} type="button" className="linkish ref" onClick={() => open(claim)} title="Evidence">
          [{i + 1}]
        </button>
      ))}{" "}
      {s.main_badge && <Badge badge={s.main_badge} />}{" "}
      {s.status_word && s.status_word !== "Confirmed" && <span className="chip">{s.status_word}</span>}
    </p>
  );
}

function Answer({ answer }: { answer: AskResponse }) {
  const [showTrace, setShowTrace] = useState(false);
  return (
    <div>
      {answer.sentences.map((s, i) => (
        <Sentence key={i} s={s} />
      ))}
      <div className="row small muted">
        {answer.graph_used && <span className="chip info">used the knowledge graph</span>}
        {answer.trace && (
          <button type="button" className="linkish" onClick={() => setShowTrace((v) => !v)}>
            {showTrace ? "Hide" : "Why this answer"}
          </button>
        )}
      </div>
      {showTrace && answer.trace && <Trace trace={answer.trace as TraceShape} />}
    </div>
  );
}

interface TraceShape {
  classification?: { question_type?: string; slot_ids?: string[]; merged_from_previous?: string[] };
  routes?: Record<string, { candidates: [string, number][]; status: string; ms: number; note?: string }>;
  removed?: Record<string, number>;
  anchored?: string[];
  gaps_attached?: string[];
  bundle?: string[];
  post_check?: { removed: number; repaired: unknown[]; first_pass_survival: number };
  stores_read?: Record<string, boolean>;
}

/** The retrieval trace (LLD-5 §10), for the presenter: DS-5 "why this answer". */
function Trace({ trace }: { trace: TraceShape }) {
  const c = trace.classification ?? {};
  return (
    <div className="stack small" style={{ marginTop: "0.75rem" }}>
      <p>
        <strong>Understood as</strong> {c.question_type} about {(c.slot_ids ?? []).join(", ") || "no named question"}
        {c.merged_from_previous?.length ? ` (carried over: ${c.merged_from_previous.join(", ")})` : ""}.
      </p>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr className="muted">
            <th align="left">Route</th>
            <th align="left">Found</th>
            <th align="left">Status</th>
            <th align="right">ms</th>
          </tr>
        </thead>
        <tbody>
          {Object.entries(trace.routes ?? {}).map(([route, r]) => (
            <tr key={route}>
              <td>{ROUTES[route] ?? route}</td>
              <td>{r.candidates.length}</td>
              <td>
                {r.status}
                {r.note ? ` (${r.note})` : ""}
              </td>
              <td align="right">{r.ms}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p>
        <strong>Checked again in Postgres:</strong> removed{" "}
        {Object.entries(trace.removed ?? {})
          .map(([why, n]) => `${n} ${why.replace(/_/g, " ")}`)
          .join(", ") || "nothing"}
        . <strong>Added as the slot's best fact:</strong> {trace.anchored?.length ?? 0}.{" "}
        <strong>In the evidence bundle:</strong> {trace.bundle?.length ?? 0}.
      </p>
      {trace.post_check && (
        <p>
          <strong>Code check of the answer:</strong> {trace.post_check.removed} removed, {trace.post_check.repaired.length}{" "}
          repaired, {Math.round(trace.post_check.first_pass_survival * 100)}% passed first time.
        </p>
      )}
      {trace.stores_read && (
        <p>
          <strong>Stores read:</strong>{" "}
          {Object.entries(trace.stores_read)
            .filter(([, read]) => read)
            .map(([store]) => store)
            .join(", ")}
        </p>
      )}
    </div>
  );
}

const ROUTES: Record<string, string> = {
  R1: "Structured facts",
  R2: "Keyword",
  R3: "Meaning (vector)",
  R4: "Knowledge graph",
};
