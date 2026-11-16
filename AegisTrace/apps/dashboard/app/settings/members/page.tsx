// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import { useState } from "react";
import { ApiError, api, timeAgo, toast, useLive } from "@/lib/client";
import { Empty, PageHeader, Panel, Skeleton } from "@/components/ui";

interface Member { subject: string; role: string; added_by: string; created_at: string }
interface Me { subject: string; role: string | null; scopes: string[] }

const ROLES: [string, string][] = [
  ["owner", "Everything, including managing owners and admins"],
  ["admin", "Rules, approvals, erasure, API keys and members"],
  ["developer", "Build and run agents, read run content and memories"],
  ["viewer", "Read runs, agents and the audit log; no run content"],
];

export default function Members() {
  const list = useLive<{ items: Member[] }>("v1/members", 15000);
  const me = useLive<Me>("v1/me", 60000);
  const [subject, setSubject] = useState("");
  const [role, setRole] = useState("developer");
  const canManage = !!me.data?.scopes.includes("members:manage");
  const isOwner = me.data?.role === "owner";
  const allowed = (r: string) => canManage && (isOwner || r !== "owner");

  async function call(path: string, init: Parameters<typeof api>[1], ok: string) {
    try { await api(path, init); toast(ok, "ok"); list.reload(); return true; }
    catch (err) { toast(err instanceof ApiError ? err.message : "That did not work", "bad"); return false; }
  }

  return (
    <>
      <PageHeader title="Members" subtitle="Who can act in this organization. A person's permissions are what their role allows, and never more than their sign-in provider allows." />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        <Panel title="People">
          {!list.data ? <Skeleton rows={4} /> : list.data.items.length === 0 ? <Empty>No members yet.</Empty> : (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead><tr><th>Person</th><th>Role</th><th>Added</th><th /></tr></thead>
                <tbody>
                  {list.data.items.map((m) => {
                    const editable = allowed(m.role) && m.subject !== me.data?.subject;
                    return (
                      <tr key={m.subject}>
                        <td className="mono text-[13px]">{m.subject}{m.subject === me.data?.subject ? <span className="muted"> (you)</span> : null}</td>
                        <td>
                          {editable ? (
                            <select aria-label={`Role for ${m.subject}`} className="input" value={m.role}
                                    onChange={(e) => call(`v1/members/${encodeURIComponent(m.subject)}`, { method: "PUT", json: { role: e.target.value } }, "Role changed")}>
                              {ROLES.filter(([r]) => allowed(r)).map(([r]) => <option key={r} value={r}>{r}</option>)}
                            </select>
                          ) : <span className="text-2">{m.role}</span>}
                        </td>
                        <td className="muted whitespace-nowrap">{timeAgo(m.created_at)} by <span className="mono">{m.added_by}</span></td>
                        <td className="text-right">{editable ? (
                          <button className="btn btn-ghost" type="button" onClick={() => call(`v1/members/${encodeURIComponent(m.subject)}`, { method: "DELETE" }, "Member removed")}>Remove</button>
                        ) : null}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        <div className="flex flex-col gap-4">
          {canManage ? (
            <Panel title="Add a person">
              <form className="flex flex-col gap-3 p-4" onSubmit={async (e) => {
                e.preventDefault();
                if (await call(`v1/members/${encodeURIComponent(subject.trim())}`, { method: "PUT", json: { role } }, "Member added")) setSubject("");
              }}>
                <label className="flex flex-col gap-1 text-[12.5px] muted">User ID from your sign-in provider
                  <input id="member-subject" className="input mono" required value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="usr_…" />
                </label>
                <label className="flex flex-col gap-1 text-[12.5px] muted">Role
                  <select id="member-role" className="input" value={role} onChange={(e) => setRole(e.target.value)}>
                    {ROLES.filter(([r]) => allowed(r)).map(([r]) => <option key={r} value={r}>{r}</option>)}
                  </select>
                </label>
                <button className="btn btn-green h-9 justify-center" type="submit" disabled={!subject.trim()}>Add</button>
              </form>
            </Panel>
          ) : null}
          <Panel title="Roles">
            <ul className="divide-y hairline">
              {ROLES.map(([r, d]) => (
                <li key={r} className="px-4 py-3 text-[13px]"><span className="font-medium">{r}</span><span className="block muted">{d}</span></li>
              ))}
            </ul>
            <p className="px-4 pb-4 text-[12.5px] muted">An organization always keeps at least one owner. Only owners can add or change owners.</p>
          </Panel>
        </div>
      </div>
    </>
  );
}
