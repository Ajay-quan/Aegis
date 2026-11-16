"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { useEffect, useRef, useState } from "react";
import { PageHeader, Panel, Badge } from "@/components/ui";

interface Ready { status: string; checks: Record<string, string>; latency_ms: number | null }

export default function Operations() {
  const [ready, setReady] = useState<Ready | null>(null);
  const [history, setHistory] = useState<(number | null)[]>([]);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const r: Ready = await (await fetch("/api/health", { cache: "no-store" })).json();
        if (!alive) return;
        setReady(r);
        setHistory((h) => [...h.slice(-59), r.status === "ok" ? r.latency_ms : null]);
      } catch { setHistory((h) => [...h.slice(-59), null]); }
      if (alive) timer.current = setTimeout(tick, 2000);
    };
    tick();
    return () => { alive = false; if (timer.current) clearTimeout(timer.current); };
  }, []);

  const max = Math.max(5, ...history.filter((x): x is number => x !== null));
  const checks = { api: ready ? (ready.status === "unreachable" ? "down" : "ok") : "…", ...(ready?.checks ?? {}) };
  return (
    <>
      <PageHeader title="System health" subtitle="Are AegisTrace’s own services up? Checked every 2 seconds." />
      <div className="grid gap-3 sm:grid-cols-3">
        {Object.entries(checks).map(([k, v]) => (
          <div key={k} className="panel flex items-center justify-between px-4 py-4">
            <span className="text-[14px] capitalize">{k}</span><Badge value={v} label={v === "ok" ? "healthy" : v} />
          </div>
        ))}
      </div>
      <Panel className="mt-4" title="Readiness probe latency" actions={<span className="mono text-[12.5px] muted">{ready?.latency_ms ?? "—"} ms · last 2 min</span>}>
        <div className="flex h-32 items-end gap-[3px] p-4">
          {history.map((v, i) => (
            <div key={i} className="flex-1 rounded-sm transition-all duration-300"
                 title={v === null ? "failed" : `${v} ms`}
                 style={{ height: v === null ? "100%" : `${Math.max(4, (v / max) * 100)}%`, background: v === null ? "var(--red)" : "#3a3f47", opacity: v === null ? 0.6 : 1 }} />
          ))}
        </div>
      </Panel>
      <p className="mt-4 text-[13px] muted">
        Queue depth, outbox lag, policy latency and recovery counters are exported as Prometheus metrics by the worker
        (:9101) and dispatcher (:9102). Alert rules live in <span className="mono">infra/observability/alerts.yml</span>.
      </p>
    </>
  );
}
