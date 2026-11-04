// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

const PAGES = [
  ["Overview", "/"], ["Insights report", "/insights"], ["Organization rules", "/rules"], ["Runs", "/runs"], ["Approvals", "/approvals"], ["Agents & permissions", "/agents"],
  ["Security", "/security"], ["System health", "/operations"], ["Start a new run", "/runs?new=1"],
] as const;

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  const router = useRouter();
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setOpen((o) => !o); }
      if (e.key === "Escape") setOpen(false);
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener("open-palette", onOpen);
    return () => { window.removeEventListener("keydown", onKey); window.removeEventListener("open-palette", onOpen); };
  }, []);
  useEffect(() => { if (open) { setQ(""); setI(0); setTimeout(() => input.current?.focus(), 10); } }, [open]);

  const items = useMemo(() => {
    const base: { label: string; hint: string; href: string }[] = PAGES
      .filter(([l]) => l.toLowerCase().includes(q.toLowerCase()))
      .map(([label, href]) => ({ label, hint: "Go to", href }));
    const id = q.trim();
    if (/^run_[a-f0-9]{24}$/.test(id)) base.unshift({ label: id, hint: "Open run", href: `/runs/${id}` });
    else if (id.length >= 3) base.push({ label: `Search runs for “${id}”`, hint: "Search", href: `/runs?q=${encodeURIComponent(id)}` });
    return base;
  }, [q]);

  if (!open) return null;
  const go = (href: string) => { setOpen(false); router.push(href); };
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[14vh]" role="dialog" aria-modal="true" aria-label="Command palette">
      <div className="absolute inset-0 bg-black/60 fade-in" onClick={() => setOpen(false)} />
      <div className="relative w-full max-w-[540px] overflow-hidden rounded-xl border fade-in shadow-2xl"
           style={{ background: "var(--panel)", borderColor: "var(--border-strong)" }}>
        <input ref={input} value={q} onChange={(e) => { setQ(e.target.value); setI(0); }}
               onKeyDown={(e) => {
                 if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(items.length - 1, x + 1)); }
                 if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(0, x - 1)); }
                 if (e.key === "Enter" && items[i]) go(items[i].href);
               }}
               placeholder="Jump to a page, or paste a run id…" aria-label="Command"
               className="h-12 w-full border-b bg-transparent px-4 text-[15px] outline-none hairline" />
        <ul className="max-h-[320px] overflow-y-auto p-1.5" role="listbox">
          {items.map((it, k) => (
            <li key={it.href + it.label} role="option" aria-selected={k === i}>
              <button onMouseEnter={() => setI(k)} onClick={() => go(it.href)}
                      className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-[14px]"
                      style={{ background: k === i ? "var(--hover)" : undefined }}>
                <span className={it.label.startsWith("run_") ? "mono" : ""}>{it.label}</span>
                <span className="text-[12px] muted">{it.hint}</span>
              </button>
            </li>
          ))}
          {items.length === 0 ? <li className="px-3 py-6 text-center text-[13.5px] muted">No matches</li> : null}
        </ul>
        <div className="flex gap-3 border-t px-4 py-2 text-[12px] muted hairline">
          <span><span className="kbd">↑↓</span> move</span><span><span className="kbd">↵</span> open</span><span><span className="kbd">esc</span> close</span>
        </div>
      </div>
    </div>
  );
}
