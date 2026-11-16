// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import { timeAgo, useLive } from "@/lib/client";
import { Empty, LiveIndicator, PageHeader, Panel, Skeleton } from "@/components/ui";

interface Ev { id: number; actor_id: string; action: string; target: string; detail: Record<string, unknown>; created_at: string }

const ACTION: Record<string, string> = { "api_key.created": "Created API key", "api_key.revoked": "Revoked API key" };

export default function Audit() {
  const live = useLive<{ items: Ev[] }>("v1/audit-events?limit=200", 10000);
  const items = live.data?.items ?? [];
  return (
    <>
      <PageHeader title="Audit log" subtitle="Administrative actions in this organization: who did what, and when. Entries cannot be edited or deleted."
                  actions={<LiveIndicator updatedAt={live.updatedAt} error={live.error} />} />
      <Panel>
        {!live.data ? <Skeleton rows={5} /> : items.length === 0 ? <Empty>No administrative actions yet.</Empty> : (
          <div className="overflow-x-auto">
            <table className="tbl">
              <thead><tr><th>When</th><th>Action</th><th>Target</th><th>By</th><th>Details</th></tr></thead>
              <tbody>
                {items.map((e) => (
                  <tr key={e.id}>
                    <td className="muted whitespace-nowrap">{timeAgo(e.created_at)}</td>
                    <td>{ACTION[e.action] ?? e.action}</td>
                    <td className="mono muted">{e.target}</td>
                    <td className="mono muted">{e.actor_id}</td>
                    <td className="text-[12.5px] text-2">{Object.entries(e.detail).filter(([, v]) => v !== null).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(", ") : String(v)}`).join(" · ")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </>
  );
}
