"use client";
// Who is signed in (GET /api/v1/session). Every screen sits behind the access gate; the
// presenter's overlay shows for the admin role only (LLD-4 §3.1, §12).
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { ApiError, del, get, post, type SessionInfo } from "@/lib/api";

type State = { status: "loading" } | { status: "out" } | { status: "in"; role: SessionInfo["role"] };

interface SessionValue {
  state: State;
  isAdmin: boolean;
  signIn: (code: string) => Promise<void>;
  signOut: () => Promise<void>;
  expired: () => void;
}

const Ctx = createContext<SessionValue | null>(null);

export function SessionProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State>({ status: "loading" });

  const refresh = useCallback(async () => {
    try {
      const info = await get<SessionInfo>("/session");
      setState({ status: "in", role: info.role });
    } catch {
      setState({ status: "out" });
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const signIn = useCallback(
    async (code: string) => {
      await post("/session", { access_code: code });
      await refresh();
    },
    [refresh],
  );
  const signOut = useCallback(async () => {
    await del("/session").catch(() => undefined);
    setState({ status: "out" });
  }, []);
  const expired = useCallback(() => setState({ status: "out" }), []);

  const isAdmin = state.status === "in" && state.role === "admin";
  return <Ctx.Provider value={{ state, isAdmin, signIn, signOut, expired }}>{children}</Ctx.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(Ctx);
  if (!value) throw new Error("useSession outside SessionProvider");
  return value;
}

/** Shows the access form until a session exists; a 401 later sends the user back here. */
export function AccessGate({ children }: { children: ReactNode }) {
  const { state, signIn } = useSession();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (state.status === "loading") return <p className="muted">Loading…</p>;
  if (state.status === "in") return <>{children}</>;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await signIn(code.trim());
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Sign-in failed. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card stack" onSubmit={submit} style={{ maxWidth: "26rem", margin: "3rem auto" }}>
      <h1>Sign in</h1>
      <p className="muted">Enter the access code you were given to research and explore cities.</p>
      <label className="field">
        <span>Access code</span>
        <input
          type="password"
          autoComplete="current-password"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
          aria-label="Access code"
        />
      </label>
      {error && <p className="error" role="alert">{error}</p>}
      <button className="button" type="submit" disabled={busy || !code.trim()}>
        {busy ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}

/** Turns an API error into a message; a lost session returns the user to the gate. */
export function useApiError(): (e: unknown) => string {
  const { expired } = useSession();
  return useCallback(
    (e: unknown) => {
      if (e instanceof ApiError) {
        if (e.status === 401) expired();
        return e.message;
      }
      return "Something went wrong. Try again.";
    },
    [expired],
  );
}
