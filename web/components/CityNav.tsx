"use client";
import Link from "next/link";

const TABS = [
  { key: "brief", label: "City brief", href: "/city/" },
  { key: "explore", label: "Explore", href: "/city/explore/" },
  { key: "ask", label: "Ask", href: "/city/ask/" },
] as const;

export function CityNav({ cityId, current }: { cityId: string; current: (typeof TABS)[number]["key"] }) {
  return (
    <nav className="tabs" aria-label="City">
      {TABS.map((t) => (
        <Link
          key={t.key}
          href={`${t.href}?id=${encodeURIComponent(cityId)}`}
          aria-current={t.key === current ? "page" : undefined}
        >
          {t.label}
        </Link>
      ))}
    </nav>
  );
}
