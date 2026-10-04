"use client";
import Link from "next/link";
import { useSession } from "./Session";

export function TopBar() {
  const { state, isAdmin, signOut } = useSession();
  return (
    <header className="topbar">
      <Link href="/" className="brand">
        CARDIO<span>4</span>Cities <span className="muted small" style={{ fontWeight: 400 }}>research</span>
      </Link>
      {state.status === "in" && (
        <div className="row">
          {isAdmin && (
            <Link href="/admin/" className="chip info" title="Presenter tools">
              Presenter
            </Link>
          )}
          <button className="button quiet" type="button" onClick={() => void signOut()}>
            Sign out
          </button>
        </div>
      )}
    </header>
  );
}
