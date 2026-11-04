"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import Link from "next/link";
import { useState } from "react";
import { api, timeAgo, toast, useLive } from "@/lib/client";
import { RISK, type Approval } from "@/lib/types";
import { Badge, Empty, JsonView, LiveIndicator, PageHeader, Skeleton } from "@/components/ui";

function Countdown({ until }: { until: string }) {
  const ms = new Date(until).getTime() - Date.now();
  if (ms <= 0) return <span style={{ color: "var(--red)" }}>expired</span>;
  const m = Math.floor(ms / 60000);
  return <span className="tnum">{m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`} left</span>;
}

export default function Approvals() {
  const [status, setStatus] = useState("pending");
  const live = useLive<{ items: Approval[] }>(`v1/approvals?status=${status}`, 2500);
  const [busy, setBusy] = useState<string | null>(null);

  async function decide(a: Approval, approve: boolean) {
    setBusy(a.id);
    try {
      await api(`v1/approvals/${a.id}/decision`, { method: "POST", json: { approve } });
      toast(approve ? `Approved ${a.tool}` : `Rejected ${a.tool}`, approve ? "ok" : "bad");
      live.reload();
    } catch (e) { toast(e instanceof Error ? e.message : "Decision failed", "bad"); }
    finally { setBusy(null); }
  }

  return (
    <>
      <PageHeader title="Approvals" subtitle="Agents asked to do something risky. Approve to let that exact action run once — nothing else."
                  actions={<LiveIndicator updatedAt={live.updatedAt} error={live.error} />} />
      <div className="mb-4 flex gap-2">
        {["pending", "consumed", "rejected", "expired"].map((s) => (
          <button key={s} className="chip" data-active={status === s} onClick={() => setStatus(s)}>{s}</button>
        ))}
      </div>
      {!live.data ? <Skeleton /> : live.data.items.length === 0 ? (
        <div className="panel"><Empty>{status === "pending" ? "Nothing waiting. Agents requesting consequential actions will appear here." : `No ${status} approvals.`}</Empty></div>
      ) : (
        <ul className="grid gap-3 lg:grid-cols-2">
          {live.data.items.map((a) => {
            const args = (a.summary as { arguments?: unknown }).arguments;
            return (
              <li key={a.id} className="panel p-4 fade-in">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="mono text-[15px] font-medium">{a.tool}</div>
                    <div className="mt-1 text-[12.5px] muted">
                      Class {a.risk_class} · {RISK[a.risk_class]} · requested {timeAgo(a.requested_at)}
                    </div>
                  </div>
                  {status === "pending" ? <span className="text-[12.5px] muted"><Countdown until={a.expires_at} /></span> : <Badge value={a.status} />}
                </div>
                <div className="mt-3 grid grid-cols-[70px_1fr] gap-y-1 text-[13px]">
                  <span className="muted">agent</span><span className="mono truncate">{a.agent_id}</span>
                  <span className="muted">run</span><Link href={`/runs/${a.run_id}`} className="mono truncate hover:underline">{a.run_id}</Link>
                  {a.decided_by ? <><span className="muted">decided by</span><span className="mono">{a.decided_by}</span></> : null}
                </div>
                <div className="mt-3"><JsonView value={args ?? a.summary} /></div>
                {status === "pending" ? (
                  <div className="mt-3 flex gap-2">
                    <button className="btn btn-green" disabled={busy === a.id} onClick={() => decide(a, true)}>Approve this exact action</button>
                    <button className="btn btn-red" disabled={busy === a.id} onClick={() => decide(a, false)}>Reject</button>
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </>
  );
}
