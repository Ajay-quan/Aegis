// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import Link from "next/link";
import { useState } from "react";
import { timeAgo, useLive } from "@/lib/client";
import type { Approval, Run, Stats } from "@/lib/types";
import { Legend, Sparkline, StackedBars, type Point, type Series } from "@/components/ActivityChart";
import { Badge, Empty, InfoTip, LiveIndicator, Panel, Skeleton } from "@/components/ui";

type Range = "1h" | "24h" | "7d";
const RANGE_LABEL: Record<Range, string> = { "1h": "last hour", "24h": "last 24 hours", "7d": "last 7 days" };

const RUN_SERIES: Series[] = [
  { key: "succeeded", label: "Succeeded", color: "var(--series-good)" },
  { key: "failed", label: "Failed", color: "var(--series-bad)" },
];
const ACTION_SERIES: Series[] = [
  { key: "allowed", label: "Allowed", color: "var(--series-good)" },
  { key: "approval", label: "Sent for approval", color: "var(--series-info)" },
  { key: "denied", label: "Blocked", color: "var(--series-bad)" },
];


function Kpi({ label, value, sub, info, spark, color, href, tone }: {
  label: string; value: string; sub: string; info: string; spark?: number[]; color?: string; href?: string;
  tone?: "amber";
}) {
  const body = (
    <div className={`panel h-full p-4 transition-colors ${href ? "hover:border-[#3a3f47]" : ""}`}
         style={tone === "amber" ? { borderColor: "rgba(229,162,58,.35)" } : undefined}>
      <div className="flex items-center gap-1.5 text-[13px] muted">{label}<InfoTip text={info} /></div>
      <div className="mt-2 flex items-end justify-between gap-3">
        <div>
          <div className="text-[28px] font-semibold leading-none tracking-tight tnum" style={tone === "amber" ? { color: "var(--amber)" } : undefined}>{value}</div>
          <div className="mt-2 text-[12.5px] muted">{sub}</div>
        </div>
        {spark && color ? <div className="w-[110px] pb-1"><Sparkline values={spark} color={color} /></div> : null}
      </div>
    </div>
  );
  return href ? <Link href={href} className="block">{body}</Link> : body;
}

export default function Overview() {
  const [range, setRange] = useState<Range>("1h");
  const [metric, setMetric] = useState<"actions" | "runs">("actions");
  const [table, setTable] = useState(false);
  const ts = useLive<{ points: Point[]; step: string; range: string }>(`v1/stats/timeseries?range=${range}`, 4000);
  const stats = useLive<Stats>("v1/stats", 4000);
  const runs = useLive<{ items: Run[] }>("v1/runs?limit=6", 4000);
  const pending = useLive<{ items: Approval[] }>("v1/approvals?status=pending", 4000);

  const pts = ts.data?.points ?? [];
  const sum = (k: string) => pts.reduce((a, p) => a + Number(p[k] ?? 0), 0);
  const succeeded = sum("succeeded"), failed = sum("failed"), blocked = sum("denied"), allowed = sum("allowed");
  const finished = succeeded + failed;
  const rate = finished ? (succeeded / finished) * 100 : null;
  const attention = (stats.data?.pending_approvals ?? 0) + (stats.data?.runs_by_state.NEEDS_RECONCILIATION ?? 0);
  const stale = ts.data && ts.data.range !== range;
  const series = metric === "runs" ? RUN_SERIES : ACTION_SERIES;
  const loaded = ts.data && stats.data;

  const health = !loaded ? null : attention > 0
    ? { tone: "amber" as const, text: `${attention} item${attention > 1 ? "s" : ""} need${attention > 1 ? "" : "s"} your attention`, href: "/approvals" }
    : failed > 0
      ? { tone: "bad" as const, text: `${failed} run${failed > 1 ? "s" : ""} failed in the ${RANGE_LABEL[range]}`, href: "/runs?state=FAILED" }
      : { tone: "good" as const, text: "All clear — agents are running within policy", href: null };
  const hc = health?.tone === "good" ? "var(--green)" : health?.tone === "bad" ? "var(--red)" : "var(--amber)";

  return (
    <>
      <header className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight">Overview</h1>
          <p className="mt-1 text-[14px] muted">What your AI agents did, what was stopped, and what needs you.</p>
        </div>
        <div className="flex items-center gap-3">
          <LiveIndicator updatedAt={ts.updatedAt} error={ts.error} />
          <div className="seg" role="group" aria-label="Time range">
            {(["1h", "24h", "7d"] as Range[]).map((r) => (
              <button key={r} data-active={range === r} onClick={() => setRange(r)}>{r}</button>
            ))}
          </div>
        </div>
      </header>

      {health ? (
        <div className="mb-5 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3 fade-in"
             style={{ borderColor: `color-mix(in srgb, ${hc} 30%, transparent)`, background: `color-mix(in srgb, ${hc} 7%, transparent)` }}>
          <span className="h-2 w-2 rounded-full live-dot" style={{ background: hc }} />
          <span className="text-[14.5px] font-medium">{health.text}</span>
          <span className="text-[13.5px] muted">
            {finished.toLocaleString()} runs finished · {blocked.toLocaleString()} risky actions blocked in the {RANGE_LABEL[range]}
          </span>
          {health.href ? <Link href={health.href} className="ml-auto text-[13.5px] font-medium" style={{ color: hc }}>Review →</Link> : null}
        </div>
      ) : <div className="mb-5 h-[46px] rounded-xl live-dot" style={{ background: "var(--panel)" }} />}


      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Runs finished" value={loaded ? finished.toLocaleString() : "–"} sub={RANGE_LABEL[range]}
             info="A run is one task given to an agent, from start to finish." spark={pts.map((p) => Number(p.succeeded) + Number(p.failed))}
             color="var(--text-2)" href="/runs" />
        <Kpi label="Success rate" value={rate === null ? "—" : `${rate.toFixed(rate === 100 ? 0 : 1)}%`}
             sub={finished ? `${succeeded.toLocaleString()} of ${finished.toLocaleString()} succeeded` : "no finished runs yet"}
             info="Share of finished runs that completed successfully. Blocked actions don't count as failures — the agent continues safely." />
        <Kpi label="Risky actions blocked" value={loaded ? blocked.toLocaleString() : "–"}
             sub={allowed + blocked ? `${((blocked / (allowed + blocked)) * 100).toFixed(0)}% of tool requests` : RANGE_LABEL[range]}
             info="Tool requests your policy refused — for example an agent trying to send email it was never allowed to send. Nothing was executed."
             spark={pts.map((p) => Number(p.denied))} color="var(--series-bad)" href="/security" />
        <Kpi label="Needs your attention" value={loaded ? String(attention) : "–"}
             sub={attention ? "approvals or unclear outcomes" : "nothing waiting"} tone={attention ? "amber" : undefined}
             info="Actions waiting for a human approval, plus runs where an external action's outcome is unknown and someone must confirm it."
             href="/approvals" />
      </section>

      <Panel className="mt-4">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b hairline px-4 py-3">
          <div className="flex items-center gap-3">
            <div className="seg" role="group" aria-label="Chart metric">
              <button data-active={metric === "actions"} onClick={() => setMetric("actions")}>Agent actions</button>
              <button data-active={metric === "runs"} onClick={() => setMetric("runs")}>Runs</button>
            </div>
            <InfoTip text={metric === "actions" ? "Every tool an agent tried to use, and what your policy decided." : "Runs that finished in each time slot, by outcome."} />
          </div>
          <div className="flex items-center gap-4">
            <Legend series={series} />
            <button className="text-[13px] muted underline-offset-2 hover:underline" onClick={() => setTable((t) => !t)}>
              {table ? "Chart" : "Table"}
            </button>
          </div>
        </div>
        <div className="px-2 pb-2 pt-3">
          {!ts.data ? <Skeleton rows={5} /> : table ? (
            <div className="max-h-[230px] overflow-y-auto px-2">
              <table className="tbl"><thead><tr><th>Time</th>{series.map((s) => <th key={s.key} className="text-right">{s.label}</th>)}</tr></thead>
                <tbody>{[...pts].reverse().filter((p) => series.some((s) => Number(p[s.key]))).map((p) => (
                  <tr key={p.t}><td className="muted">{new Date(p.t).toLocaleString()}</td>
                    {series.map((s) => <td key={s.key} className="text-right tnum">{Number(p[s.key])}</td>)}</tr>))}
                </tbody></table>
            </div>
          ) : <StackedBars points={pts} series={series} step={ts.data.step} dim={!!stale} />}
        </div>
      </Panel>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Panel title="Needs your attention" actions={<Link href="/approvals" className="text-[13px] muted hover:text-[var(--text)]">All approvals →</Link>}>
          {!pending.data ? <Skeleton rows={3} /> : pending.data.items.length === 0 ? (
            <Empty>Nothing is waiting for you. Risky actions will show up here for approval.</Empty>
          ) : (
            <ul>
              {pending.data.items.slice(0, 5).map((a) => (
                <li key={a.id} className="flex items-center justify-between gap-3 border-b px-4 py-3 last:border-0 hairline">
                  <div className="min-w-0">
                    <div className="text-[14px]"><span className="mono">{a.tool}</span> <span className="muted">wants approval</span></div>
                    <div className="mt-0.5 truncate text-[12.5px] muted">requested {timeAgo(a.requested_at)} · run <span className="mono">{a.run_id.slice(0, 14)}…</span></div>
                  </div>
                  <Link href="/approvals" className="btn h-7 shrink-0" style={{ color: "var(--amber)", borderColor: "rgba(229,162,58,.35)", background: "var(--amber-bg)" }}>Review</Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="Latest runs" actions={<Link href="/runs" className="text-[13px] muted hover:text-[var(--text)]">All runs →</Link>}>
          {!runs.data ? <Skeleton rows={3} /> : runs.data.items.length === 0 ? <Empty>No runs yet. Start one from the Runs page.</Empty> : (
            <ul>
              {runs.data.items.map((r) => (
                <li key={r.id}>
                  <Link href={`/runs/${r.id}`} className="flex items-center justify-between gap-3 border-b px-4 py-2.5 transition-colors hover:bg-[var(--hover)] hairline">
                    <span className="mono truncate text-[13.5px] text-2">{r.id}</span>
                    <span className="flex shrink-0 items-center gap-3"><Badge value={r.state} /><span className="w-16 text-right text-[12.5px] muted">{timeAgo(r.updated_at)}</span></span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </>
  );
}
