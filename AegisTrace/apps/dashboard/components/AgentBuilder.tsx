"use client";
// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Agent Builder: configure an agent, keep every version, and try it on a task.
import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, api, timeAgo, toast, useLive } from "@/lib/client";
import { Panel, Skeleton } from "@/components/ui";

interface AgentCfg {
  id: string; project_id: string; name: string; model_provider: string; model_id: string; instructions: string;
  max_steps: number; memory_enabled: boolean; version: number; updated_at: string;
}
interface Version { version: number; changed_by: string; note: string | null; created_at: string; config: Partial<AgentCfg> }
interface Model { id: string; name: string; provider: string; model_id: string; status: string; runnable: boolean }

export function NewAgent({ onCreated }: { onCreated: (id: string) => void }) {
  const projects = useLive<{ items: { id: string; name: string }[] }>("v1/projects", 60000);
  const [name, setName] = useState("");
  const [project, setProject] = useState("");
  const first = projects.data?.items[0]?.id ?? "";
  return (
    <form className="flex flex-col gap-2 border-b hairline p-3" onSubmit={async (e) => {
      e.preventDefault();
      try {
        const r = await api<{ id: string }>("v1/agents", { method: "POST", json: { project_id: project || first, name: name.trim() } });
        toast("Agent created with no permissions. Give it tools below.", "ok"); setName(""); onCreated(r.id);
      } catch (err) { toast(err instanceof ApiError ? err.message : "Could not create the agent", "bad"); }
    }}>
      <input id="new-agent-name" className="input" required maxLength={100} placeholder="New agent name" value={name} onChange={(e) => setName(e.target.value)} />
      {projects.data && projects.data.items.length > 1 ? (
        <select aria-label="Workspace" className="input" value={project || first} onChange={(e) => setProject(e.target.value)}>
          {projects.data.items.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      ) : null}
      <button className="btn btn-green justify-center" type="submit" disabled={!name.trim() || !first}>Create agent</button>
    </form>
  );
}

export function AgentBuilder({ agentId, onSaved }: { agentId: string; onSaved: () => void }) {
  const agent = useLive<AgentCfg>(`v1/agents/${agentId}`, 30000);
  const models = useLive<{ items: Model[] }>("v1/models", 60000);
  const versions = useLive<{ items: Version[] }>(`v1/agents/${agentId}/versions`, 30000);
  const [draft, setDraft] = useState<AgentCfg | null>(null);
  const [note, setNote] = useState("");
  const [task, setTask] = useState("");
  const [lastRun, setLastRun] = useState<string | null>(null);

  useEffect(() => { if (agent.data && (!draft || draft.id !== agent.data.id)) setDraft(agent.data); }, [agent.data, draft]);
  if (!draft) return <Panel title="Agent"><Skeleton rows={4} /></Panel>;
  const a = agent.data!;
  const dirty = (["name", "model_provider", "model_id", "instructions", "max_steps", "memory_enabled"] as const).some((k) => draft[k] !== a[k]);
  const modelValue = draft.model_provider === "registry" ? draft.model_id : "demo";

  async function save() {
    const changes: Record<string, unknown> = { note: note || null };
    for (const k of ["name", "model_provider", "model_id", "instructions", "max_steps", "memory_enabled"] as const) if (draft![k] !== a[k]) changes[k] = draft![k];
    try {
      const r = await api<AgentCfg>(`v1/agents/${agentId}`, { method: "PUT", json: changes });
      toast(`Saved as version ${r.version}`, "ok"); setNote(""); setDraft(r); agent.reload(); versions.reload(); onSaved();
    } catch (err) { toast(err instanceof ApiError ? err.message : "Could not save", "bad"); }
  }

  async function tryIt(e: React.FormEvent) {
    e.preventDefault();
    try {
      const r = await api<{ id: string }>("v1/runs", { method: "POST", json: { agent_id: agentId, input: { task } },
        headers: { "Idempotency-Key": `studio-${crypto.randomUUID()}` } });
      setLastRun(r.id); toast("Run started", "ok");
    } catch (err) { toast(err instanceof ApiError ? err.message : "Could not start the run", "bad"); }
  }

  return (
    <Panel title={<span>Agent <span className="muted">· version {a.version}</span></span>}>
      <div className="grid gap-4 p-4 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          <label className="flex flex-col gap-1 text-[12.5px] muted">Name
            <input id="agent-name" className="input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] muted">Model
            <select id="agent-model" className="input" value={modelValue} onChange={(e) => {
              const v = e.target.value;
              setDraft(v === "demo" ? { ...draft, model_provider: "mock", model_id: "mock-deterministic-1" } : { ...draft, model_provider: "registry", model_id: v });
            }}>
              <option value="demo">Demo model (deterministic)</option>
              {models.data?.items.map((m) => (
                <option key={m.id} value={m.id} disabled={!m.runnable}>{m.name} · {m.provider}/{m.model_id}{m.runnable ? (m.status === "connected" ? "" : " · not tested") : " · cannot run agents yet"}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] muted">Instructions
            <textarea id="agent-instructions" className="input" rows={5} maxLength={8000} value={draft.instructions}
                      placeholder="What this agent is for and how it should behave. Permissions are enforced separately."
                      onChange={(e) => setDraft({ ...draft, instructions: e.target.value })} />
          </label>
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-1 text-[12.5px] muted">Step limit
              <input id="agent-steps" className="input w-24" type="number" min={1} max={50} value={draft.max_steps}
                     onChange={(e) => setDraft({ ...draft, max_steps: Math.max(1, Math.min(50, Number(e.target.value) || 1)) })} />
            </label>
            <label className="flex items-center gap-2 pb-2 text-[13px]">
              <input id="agent-memory" type="checkbox" className="h-4 w-4 accent-[var(--green)]" checked={draft.memory_enabled}
                     onChange={(e) => setDraft({ ...draft, memory_enabled: e.target.checked })} />
              Memory (recall and remember through AegisMem)
            </label>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <input id="agent-note" className="input min-w-[180px] flex-1" placeholder="What changed (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
            <button className="btn btn-green" type="button" disabled={!dirty} onClick={save}>Save new version</button>
            {dirty ? <button className="btn btn-ghost" type="button" onClick={() => setDraft(a)}>Discard</button> : null}
          </div>
          <p className="text-[12px] muted">Turning memory on or off changes the agent&apos;s permissions, so it needs an admin.</p>
        </div>

        <div className="flex flex-col gap-4">
          <form className="flex flex-col gap-2" onSubmit={tryIt}>
            <span className="text-[12.5px] muted">Try it</span>
            <textarea id="agent-task" className="input" rows={2} required placeholder="A task for this agent" value={task} onChange={(e) => setTask(e.target.value)} />
            <button className="btn self-start" type="submit" disabled={dirty} title={dirty ? "Save first: runs use the saved version" : undefined}>Run</button>
            {lastRun ? <Link href={`/runs/${lastRun}`} className="mono text-[12.5px] text-[var(--green)]">Open run {lastRun.slice(0, 14)}…</Link> : null}
          </form>
          <div>
            <p className="mb-1.5 text-[12.5px] muted">Versions</p>
            <ol className="max-h-56 overflow-y-auto text-[12.5px]">
              {versions.data?.items.map((v) => (
                <li key={v.version} className="border-t hairline py-1.5">
                  <span className="mono">v{v.version}</span> <span className="muted">· {timeAgo(v.created_at)} · {v.changed_by}</span>
                  {v.note ? <span className="block text-2">{v.note}</span> : null}
                </li>
              ))}
            </ol>
          </div>
        </div>
      </div>
    </Panel>
  );
}
