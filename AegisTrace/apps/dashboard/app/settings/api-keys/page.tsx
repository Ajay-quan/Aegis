// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
"use client";
import { useState } from "react";
import { ApiError, api, timeAgo, toast, useLive } from "@/lib/client";
import { Badge, Empty, PageHeader, Panel, Skeleton } from "@/components/ui";

interface Key {
  id: string; name: string; prefix: string; scopes: string[]; created_by: string; created_at: string;
  expires_at: string | null; last_used_at: string | null; revoked_at: string | null;
}
interface Created extends Pick<Key, "id" | "name" | "prefix" | "scopes" | "expires_at"> { key: string }

// What a key may do. Key management itself is never grantable to a key.
const SCOPES: [string, string][] = [
  ["runs:read", "Read runs and their events"],
  ["runs:write", "Start runs"],
  ["agents:read", "List agents and their permissions"],
  ["agents:write", "Register agents and change permissions"],
  ["approvals:read", "See approval requests"],
  ["approvals:decide", "Approve or reject actions"],
  ["receipts:export", "Download signed receipts"],
  ["replay:read", "Replay runs"],
  ["payloads:read", "Read run content and memories"],
  ["audit:read", "Read decisions and the audit log"],
];
const EXPIRY = [[30, "30 days"], [90, "90 days"], [365, "1 year"], [0, "Never"]] as const;

function status(k: Key): "active" | "revoked" | "expired" {
  if (k.revoked_at) return "revoked";
  if (k.expires_at && new Date(k.expires_at) < new Date()) return "expired";
  return "active";
}

export default function ApiKeys() {
  const keys = useLive<{ items: Key[] }>("v1/api-keys", 15000);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["runs:read"]);
  const [expiry, setExpiry] = useState(90);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<Created | null>(null);
  const [copied, setCopied] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);

  async function create(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const k = await api<Created>("v1/api-keys", {
        method: "POST", json: { name: name.trim(), scopes, expires_in_days: expiry || null },
      });
      setCreated(k); setCopied(false); setName(""); keys.reload();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Could not create the key", "bad");
    } finally { setBusy(false); }
  }

  async function revoke(id: string) {
    try { await api(`v1/api-keys/${id}`, { method: "DELETE" }); toast("Key revoked. It stops working immediately.", "ok"); keys.reload(); }
    catch (err) { toast(err instanceof ApiError ? err.message : "Could not revoke the key", "bad"); }
    finally { setConfirming(null); }
  }

  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setCopied(true); } catch { setCopied(false); }
  }

  const items = keys.data?.items ?? [];
  return (
    <>
      <PageHeader title="API keys" subtitle="Keys let SDKs, the CLI, CI jobs and agents call the Aegis API without signing in. Each key has only the permissions you give it." />

      {created ? (
        <Panel className="mb-4" title="Copy your new key now">
          <div className="p-4">
            <p className="text-[13.5px] text-2">This is the only time the full key is shown. Store it in your secret manager; Aegis keeps only a fingerprint of it.</p>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <code className="mono flex-1 min-w-0 break-all rounded-md px-3 py-2 text-[13px]" style={{ background: "var(--panel-2)", border: "1px solid var(--border)" }} data-testid="new-key">{created.key}</code>
              <button className="btn" type="button" onClick={() => copy(created.key)}>{copied ? "Copied" : "Copy"}</button>
              <button className="btn btn-ghost" type="button" onClick={() => setCreated(null)}>Done</button>
            </div>
            <p className="mt-3 text-[12.5px] muted">Use it as a bearer token: <span className="mono">Authorization: Bearer {created.prefix}…</span></p>
          </div>
        </Panel>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Panel title="Create a key">
          <form className="flex flex-col gap-4 p-4" onSubmit={create}>
            <label className="flex flex-col gap-1.5 text-[13px]">
              <span className="muted">Name</span>
              <input id="key-name" className="input" required maxLength={100} placeholder="e.g. github-actions" value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <fieldset className="flex flex-col gap-1.5">
              <legend className="mb-1.5 text-[13px] muted">Permissions</legend>
              {SCOPES.map(([s, label]) => (
                <label key={s} className="flex cursor-pointer items-start gap-2.5 rounded-md px-1 py-1 text-[13.5px] hover:bg-[var(--hover)]">
                  <input type="checkbox" className="mt-0.5 h-4 w-4 accent-[var(--green)]" checked={scopes.includes(s)}
                         onChange={(e) => setScopes((cur) => (e.target.checked ? [...cur, s] : cur.filter((x) => x !== s)))} />
                  <span><span className="mono text-[12.5px]">{s}</span><span className="block text-[12.5px] muted">{label}</span></span>
                </label>
              ))}
            </fieldset>
            <label className="flex flex-col gap-1.5 text-[13px]">
              <span className="muted">Expires</span>
              <select id="key-expiry" className="input" value={expiry} onChange={(e) => setExpiry(Number(e.target.value))}>
                {EXPIRY.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
              </select>
            </label>
            <button className="btn btn-green h-9 justify-center" type="submit" disabled={busy || !name.trim() || scopes.length === 0}>Create key</button>
            <p className="text-[12.5px] muted">You can only grant permissions you have yourself. Keys can never create other keys.</p>
          </form>
        </Panel>

        <Panel title="Keys">
          {!keys.data ? <Skeleton rows={4} /> : items.length === 0 ? <Empty>No keys yet. Create one to use the API from code.</Empty> : (
            <div className="overflow-x-auto">
              <table className="tbl">
                <thead><tr><th>Name</th><th>Key</th><th>Permissions</th><th>Last used</th><th>Expires</th><th>Status</th><th /></tr></thead>
                <tbody>
                  {items.map((k) => {
                    const st = status(k);
                    return (
                      <tr key={k.id}>
                        <td>{k.name}<span className="block text-[12px] muted">created {timeAgo(k.created_at)}</span></td>
                        <td className="mono muted">{k.prefix}…</td>
                        <td className="text-[12.5px] text-2">{k.scopes.join(", ")}</td>
                        <td className="muted whitespace-nowrap">{k.last_used_at ? timeAgo(k.last_used_at) : "never"}</td>
                        <td className="muted whitespace-nowrap">{k.expires_at ? new Date(k.expires_at).toLocaleDateString() : "never"}</td>
                        <td><Badge value={st === "active" ? "active" : st === "revoked" ? "rejected" : "expired"} label={st} /></td>
                        <td className="whitespace-nowrap text-right">
                          {st !== "active" ? null : confirming === k.id ? (
                            <span className="inline-flex gap-2">
                              <button className="btn btn-red" type="button" onClick={() => revoke(k.id)}>Revoke now</button>
                              <button className="btn btn-ghost" type="button" onClick={() => setConfirming(null)}>Keep</button>
                            </span>
                          ) : (
                            <button className="btn" type="button" onClick={() => setConfirming(k.id)}>Revoke</button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      </div>
    </>
  );
}
