import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { EvidenceProvider } from "@/components/Evidence";
import { SessionProvider } from "@/components/Session";
import { TopBar } from "@/components/TopBar";
import "./globals.css";

export const metadata: Metadata = {
  title: "CARDIO4Cities research",
  description: "Live, verified, cited briefs of a city's cardiovascular landscape.",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>
          <EvidenceProvider>
            <TopBar />
            <main className="shell">{children}</main>
          </EvidenceProvider>
        </SessionProvider>
      </body>
    </html>
  );
}
