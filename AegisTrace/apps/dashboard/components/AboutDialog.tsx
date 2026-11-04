// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { I, Icon } from "./Shell";

const FEATURES: [string, string, string, keyof typeof I][] = [
  ["/", "Overview", "What's happening right now", "overview"],
  ["/insights", "Insights", "Healthy vs. concerning agents", "insights"],
  ["/runs", "Runs", "Every task, step by step, with proof", "runs"],
  ["/approvals", "Approvals", "Risky actions waiting for your OK", "approvals"],
  ["/agents", "Agents & permissions", "Which tools each agent may use", "agents"],
  ["/rules", "Rules", "Organization-wide safety rules", "rules"],
  ["/security", "Security", "Every request and what was blocked", "security"],
  ["/operations", "System health", "Is AegisTrace itself running well", "operations"],
];

export function AboutDialog() {
  const [open, setOpen] = useState(false);
  const path = usePathname();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "i") { e.preventDefault(); setOpen((o) => !o); }
      if (e.key === "Escape") setOpen(false);
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("open-about", onOpen);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("open-about", onOpen); };
  }, []);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[10vh]" role="dialog" aria-modal="true" aria-label="About AegisTrace">
      <div className="absolute inset-0 bg-black/70 fade-in" onClick={() => setOpen(false)} />
      <div className="relative max-h-[80vh] w-full max-w-[640px] overflow-y-auto rounded-xl border fade-in shadow-2xl"
           style={{ background: "var(--panel)", borderColor: "var(--border-strong)" }}>
        <div className="flex items-start justify-between gap-4 px-6 pt-5">
          <div>
            <h2 className="text-[17px]">AegisTrace</h2>
            <p className="mt-1.5 max-w-[500px] text-[14.5px] leading-relaxed text-2">
              Keeps your AI agents in check. It decides what they&apos;re allowed to do, asks a person before
              risky actions, and keeps tamper-proof records of everything they did.
            </p>
          </div>
          <button className="btn btn-ghost h-7 shrink-0 px-2" onClick={() => setOpen(false)} aria-label="Close">✕</button>
        </div>
        <ul className="grid gap-1 p-4 sm:grid-cols-2">
          {FEATURES.map(([href, name, desc, icon]) => {
            const here = href === "/" ? path === "/" : path.startsWith(href);
            return (
              <li key={href}>
                <Link href={href} onClick={() => setOpen(false)}
                      className="flex h-full gap-3 rounded-lg border px-3 py-2.5 transition-colors hover:bg-[var(--hover)]"
                      style={{ borderColor: here ? "var(--border-strong)" : "transparent", background: here ? "var(--panel-2)" : undefined }}>
                  <span className="mt-[2px] grid h-7 w-7 shrink-0 place-items-center rounded-md"
                        style={{ background: "var(--panel-2)", border: "1px solid var(--border)", color: "var(--text-2)" }}>
                    <Icon d={I[icon]} />
                  </span>
                  <span>
                    <span className="block text-[14px] font-medium">{name}</span>
                    <span className="block text-[13px] muted leading-snug">{desc}</span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
        <div className="flex gap-4 border-t px-6 py-2.5 text-[12px] muted hairline">
          <span><span className="kbd">⌘K</span> search</span><span><span className="kbd">⌘I</span> this guide</span>
        </div>
      </div>
    </div>
  );
}
