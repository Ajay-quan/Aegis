"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { useLive } from "@/lib/client";
import { AboutDialog } from "./AboutDialog";
import { CommandPalette } from "./CommandPalette";
import { Toaster } from "./ui";

export const I = {
  overview: "M3 13h8V3H3v10zm0 8h8v-6H3v6zm10 0h8V11h-8v10zm0-18v6h8V3h-8z",
  runs: "M4 6h16M4 12h16M4 18h10",
  approvals: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z",
  agents: "M12 3l8 4v5c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V7l8-4z",
  security: "M12 9v4m0 4h.01M10.3 3.9L1.8 18a2 2 0 001.7 3h17a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
  operations: "M22 12h-4l-3 9L9 3l-3 9H2",
  insights: "M3 3v18h18M7 15l4-4 3 3 5-6",
  rules: "M4 6h10M4 12h16M4 18h7M17 4v4M20 16v4M14 18h7",
};

const NAV: [string, string, keyof typeof I][] = [
  ["/", "Overview", "overview"], ["/insights", "Insights", "insights"], ["/runs", "Runs", "runs"],
  ["/approvals", "Approvals", "approvals"], ["/agents", "Agents & permissions", "agents"], ["/rules", "Rules", "rules"], ["/security", "Security", "security"], ["/operations", "System health", "operations"],
];

export function Icon({ d }: { d: string }) {
  return (
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"
         strokeLinecap="round" strokeLinejoin="round" aria-hidden><path d={d} /></svg>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const path = usePathname();
  const { data } = useLive<{ pending_approvals: number }>(path === "/login" ? null : "v1/stats", 5000);
  if (path === "/login") return <>{children}<Toaster /></>;
  const pending = data?.pending_approvals ?? 0;
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only">Skip to content</a>
      <nav aria-label="Primary" className="hidden md:flex w-[236px] shrink-0 flex-col border-r hairline px-3 py-4 sticky top-0 h-screen">
        <div className="mb-6 flex items-center px-2">
        <Link href="/" className="flex items-center gap-2">
          <span className="grid h-6 w-6 place-items-center rounded-md" style={{ background: "var(--green-bg)", border: "1px solid rgba(62,207,142,.35)" }}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2.5"><path d={I.agents} /></svg>
          </span>
          <span className="text-[15px] font-semibold tracking-tight">AegisTrace</span>
        </Link>
        <button onClick={() => window.dispatchEvent(new Event("open-about"))} title="Guide (⌘I)" aria-label="Open guide"
                className="ml-auto grid h-7 w-7 place-items-center rounded-md muted transition-colors hover:bg-[var(--hover)] hover:text-[var(--text)]">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden>
            <circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" />
          </svg>
        </button>
        </div>
        <button onClick={() => window.dispatchEvent(new Event("open-palette"))}
                className="mb-4 flex h-8 items-center gap-2 rounded-md border px-2.5 text-left text-[13.5px] muted transition-colors hover:text-[var(--text)] hairline"
                style={{ background: "var(--bg)" }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="7" /><path d="M21 21l-4.3-4.3" /></svg>
          <span className="flex-1">Search</span><span className="kbd">⌘K</span>
        </button>
        <ul className="flex flex-col gap-0.5">
          {NAV.map(([href, label, icon]) => {
            const active = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <li key={href}>
                <Link href={href} aria-current={active ? "page" : undefined}
                      className="flex items-center gap-2.5 rounded-md px-2.5 py-[7px] text-[14px] transition-colors"
                      style={{ background: active ? "var(--hover)" : undefined, color: active ? "var(--text)" : "var(--muted)" }}>
                  <Icon d={I[icon]} />
                  <span className="flex-1">{label}</span>
                  {href === "/approvals" && pending > 0 ? (
                    <span className="rounded px-1.5 text-[11.5px] font-semibold tnum" style={{ background: "var(--amber-bg)", color: "var(--amber)" }}>{pending}</span>
                  ) : null}
                </Link>
              </li>
            );
          })}
        </ul>
        <div className="mt-auto px-2">
          <form action="/logout" method="post">
            <button className="btn btn-ghost w-full justify-start px-1">Sign out</button>
          </form>
        </div>
      </nav>
      <div className="flex-1 min-w-0">
        <nav aria-label="Primary mobile" className="md:hidden flex gap-1 overflow-x-auto border-b hairline px-3 py-2">
          {NAV.map(([href, label]) => (
            <Link key={href} href={href} className="chip" data-active={href === "/" ? path === "/" : path.startsWith(href)}>{label}</Link>
          ))}
          <button className="chip" onClick={() => window.dispatchEvent(new Event("open-about"))} aria-label="Open guide">Guide</button>
        </nav>
        <main id="main" className="mx-auto max-w-[1200px] px-5 py-7 md:px-8">{children}</main>
      </div>
      <CommandPalette />
      <AboutDialog />
      <Toaster />
    </div>
  );
}
