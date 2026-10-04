"use client";
// Presenter tools (LLD-4 §3.5, §12; DS-2): the workflow drawn from the compiled graphs,
// so the panel sees exactly what runs (AT-03). Planted trust cases arrive with D4-1.
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { get, type DiagramResponse } from "@/lib/api";
import { AccessGate, useSession } from "@/components/Session";

export default function AdminPage() {
  return (
    <AccessGate>
      <Admin />
    </AccessGate>
  );
}

function Admin() {
  const { isAdmin } = useSession();
  const [diagram, setDiagram] = useState<DiagramResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    get<DiagramResponse>("/workflow/diagram").then(setDiagram).catch((e: Error) => setError(e.message));
  }, []);

  return (
    <div className="stack">
      <h1 style={{ marginTop: "1.5rem" }}>Presenter tools</h1>
      {!isAdmin && <p className="notice">Sign in with the presenter code to switch the graph off in Ask and to see answer traces.</p>}
      <p className="muted">
        The research workflow, drawn from the code that runs it. Dotted arrows are decisions: the crawl gate, the
        independent check and the coverage loop.
      </p>
      {error && <p className="error">{error}</p>}
      {!diagram && !error && <p className="muted">Loading…</p>}
      {diagram && (
        <>
          <section className="card">
            <h2 style={{ marginTop: 0 }}>Run</h2>
            <Mermaid text={diagram.main} />
          </section>
          <section className="card">
            <h2 style={{ marginTop: 0 }}>One question (slot)</h2>
            <Mermaid text={diagram.slot} />
          </section>
        </>
      )}
      <p className="small">
        <Link href="/">Back to start</Link>
      </p>
    </div>
  );
}

function Mermaid({ text }: { text: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
        mermaid.initialize({ startOnLoad: false, theme: dark ? "dark" : "neutral", securityLevel: "strict" });
        const { svg } = await mermaid.render(`m${Math.random().toString(36).slice(2)}`, text);
        if (!cancelled && ref.current) ref.current.innerHTML = svg;
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [text]);

  if (failed) return <pre className="code">{text}</pre>;
  return <div ref={ref} style={{ overflowX: "auto" }} aria-label="Workflow diagram" />;
}
