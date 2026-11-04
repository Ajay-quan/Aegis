"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import type { ReactNode } from "react";
import { useToasts } from "@/lib/client";

const GOOD = new Set(["SUCCEEDED", "allow", "approved", "consumed", "VALID", "IDENTICAL", "ok"]);
const BAD = new Set(["FAILED", "TIMED_OUT", "NEEDS_RECONCILIATION", "deny", "rejected", "expired", "down", "DIVERGED"]);
const ACTIVE = new Set(["QUEUED", "RUNNING", "RECOVERING", "RETRY_SCHEDULED", "VALIDATING", "CREATED"]);

const ATTN = new Set(["WAITING_FOR_APPROVAL", "pending", "require_approval"]);

export function tone(value: string): "good" | "bad" | "attn" | "neutral" {
  if (GOOD.has(value)) return "good";
  if (ATTN.has(value)) return "attn";
  if (BAD.has(value) || /^(INVALID|BROKEN|MISSING|UNTRUSTED|CHECKPOINT|PAYLOAD|ARTIFACT|MANIFEST|BINDING)/.test(value))
    return "bad";
  return "neutral";
}

export function Badge({ value, label }: { value: string; label?: string }) {
  const t = tone(value);
  const color = t === "good" ? "var(--green)" : t === "bad" ? "var(--red)" : t === "attn" ? "var(--amber)" : "var(--text-2)";
  const bg = t === "good" ? "var(--green-bg)" : t === "bad" ? "var(--red-bg)" : t === "attn" ? "var(--amber-bg)" : "var(--neutral-bg)";
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-[12px] font-medium mono whitespace-nowrap"
          style={{ color, background: bg }}>
      <span aria-hidden className={`h-1.5 w-1.5 rounded-full ${ACTIVE.has(value) ? "live-dot" : ""}`}
            style={{ background: color }} />
      {label ?? (value === "WAITING_FOR_APPROVAL" ? "waiting on you" : value === "NEEDS_RECONCILIATION" ? "needs review" : value.replaceAll("_", " ").toLowerCase())}
    </span>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-[21px] font-semibold tracking-tight">{title}</h1>
        {subtitle ? <p className="mt-1 text-[14px] muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
    </header>
  );
}

export function Stat({ label, value, tone: t, hint, onClick }: {
  label: string; value: ReactNode; tone?: "good" | "bad"; hint?: string; onClick?: () => void;
}) {
  const color = t === "good" ? "var(--green)" : t === "bad" ? "var(--red)" : "var(--text)";
  const Tag = onClick ? "button" : "div";
  return (
    <Tag onClick={onClick} className={`panel p-4 text-left ${onClick ? "cursor-pointer hover:border-[#3a3f47] transition-colors" : ""}`}>
      <div className="text-[12.5px] muted">{label}</div>
      <div className="mt-2 text-[26px] font-semibold tnum leading-none" style={{ color }}>{value}</div>
      {hint ? <div className="mt-2 text-[12.5px] muted">{hint}</div> : null}
    </Tag>
  );
}

export function Panel({ title, actions, children, className = "" }: {
  title?: ReactNode; actions?: ReactNode; children: ReactNode; className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      {title ? (
        <div className="flex items-center justify-between border-b hairline px-4 py-3">
          <h2 className="text-[14px] font-medium">{title}</h2>
          {actions}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="px-4 py-10 text-center text-[14px] muted">{children}</div>;
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="p-4 space-y-3">
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="h-4 rounded live-dot" style={{ background: "var(--panel-2)", width: `${90 - i * 12}%` }} />
      ))}
    </div>
  );
}

export function Hash({ value, n = 10 }: { value?: string | null; n?: number }) {
  if (!value) return <span className="muted">—</span>;
  return <span className="mono muted" title={value}>{value.replace("sha256:", "").slice(0, n)}</span>;
}

export function JsonView({ value }: { value: unknown }) {
  return (
    <pre className="mono text-[12.5px] leading-relaxed overflow-x-auto rounded-md p-3 text-2"
         style={{ background: "var(--bg)", border: "1px solid var(--border)" }}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function Toaster() {
  const items = useToasts();
  return (
    <div aria-live="polite" className="fixed bottom-4 right-4 z-50 flex flex-col gap-2">
      {items.map((t) => (
        <div key={t.id} className="slide-in panel px-4 py-2.5 text-[13.5px] shadow-xl flex items-center gap-2"
             style={{ borderColor: t.tone === "ok" ? "rgba(62,207,142,.4)" : t.tone === "bad" ? "rgba(242,92,92,.4)" : "var(--border-strong)" }}>
          <span className="h-1.5 w-1.5 rounded-full"
                style={{ background: t.tone === "ok" ? "var(--green)" : t.tone === "bad" ? "var(--red)" : "var(--muted)" }} />
          {t.text}
        </div>
      ))}
    </div>
  );
}

export function Drawer({ open, onClose, title, children }: {
  open: boolean; onClose: () => void; title: string; children: ReactNode;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label={title}
         onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <div className="absolute inset-0 bg-black/60 fade-in" onClick={onClose} />
      <div className="slide-in absolute right-0 top-0 h-full w-full max-w-[520px] overflow-y-auto border-l hairline"
           style={{ background: "var(--panel)" }}>
        <div className="flex items-center justify-between border-b hairline px-5 py-4">
          <h2 className="text-[15px] font-medium">{title}</h2>
          <button className="btn btn-ghost" onClick={onClose} aria-label="Close">Esc</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
}

export function LiveIndicator({ updatedAt, error }: { updatedAt: number | null; error: string | null }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[12.5px] muted">
      <span className={`h-1.5 w-1.5 rounded-full ${error ? "" : "live-dot"}`}
            style={{ background: error ? "var(--red)" : "var(--green)" }} />
      {error ? "disconnected" : updatedAt ? "live" : "connecting"}
    </span>
  );
}

/** Small "?" that explains a term in plain language on hover or keyboard focus. */
export function InfoTip({ text }: { text: string }) {
  return (
    <span className="group relative inline-flex align-middle">
      <button type="button" aria-label={text}
              className="grid h-3.5 w-3.5 place-items-center rounded-full text-[9px] font-semibold"
              style={{ border: "1px solid var(--border-strong)", color: "var(--muted)" }}>?</button>
      <span role="tooltip"
            className="pointer-events-none invisible absolute left-1/2 top-5 z-30 w-[240px] -translate-x-1/2 rounded-md border px-3 py-2 text-[12.5px] font-normal leading-relaxed text-2 opacity-0 shadow-2xl transition-opacity group-hover:visible group-hover:opacity-100 group-focus-within:visible group-focus-within:opacity-100"
            style={{ background: "var(--panel-2)", borderColor: "var(--border-strong)" }}>{text}</span>
    </span>
  );
}
