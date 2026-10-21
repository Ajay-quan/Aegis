/**
 * The memory engine. Decrypted memories exist only in this object's memory while unlocked.
 *
 * Integrity rules carried over from the server product:
 *   - text that looks like injected instructions is held as "pending" and never served until approved
 *   - retired (corrected or deleted) memories are never served
 *   - erasure removes the record and returns a receipt
 *   - a newer statement on the same subject is linked to the older one and both are shown with dates
 *     (the older is never silently dropped, because the "update" link is a heuristic)
 */
import { categorize, isMemorable, redact, screen, sentences, slotOf, type Category } from "./analyze";
import { createVault, openJson, sealJson, unlockWithPassphrase, unlockWithRecovery, changePassphrase } from "./crypto";
import { BM25, jaccard } from "./search";
import { cosine, type Embedder } from "./vector";
import { store } from "./store";

export type Status = "active" | "pending" | "retired";
export type SourceKind = "user_message" | "manual" | "pasted";

export interface Memory {
  id: string;
  text: string;
  category: Category;
  status: Status;
  source: { site: string; kind: SourceKind; url?: string };
  createdAt: string; // ISO
  redactions: string[];
  flags: string[]; // matched injection phrases, if any
  slot?: string; // single-valued fact this memory sets (residence, employer, diet, relationship)
  vec?: number[]; // on-device embedding (encrypted with the record)
  updates?: string; // id of an older memory this one appears to update
  updatedBy?: string;
}

export interface Receipt {
  memoryId: string;
  erasedAt: string;
  digest: string; // sha256(memoryId|erasedAt|"erased"), lets the user show a deletion happened
  verified: boolean; // record confirmed absent from storage after deletion
}

const DUPLICATE = 0.8;
// Hybrid relevance = (1 - W) * min-max(dense) + W * min-max(BM25), the "convex 0.7" configuration
// that beat BM25 on the LongMemEval dev split in the main repo (bench/retrieval_ablation.py).
export const LEXICAL_WEIGHT = 0.7;
const POOL = 50;

function minmax(xs: Map<string, number>): Map<string, number> {
  const v = [...xs.values()];
  const lo = Math.min(...v);
  const hi = Math.max(...v);
  return new Map([...xs].map(([k, x]) => [k, hi > lo ? (x - lo) / (hi - lo) : 1]));
}
const SAME_SUBJECT = 0.3;

async function sha256(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, "0")).join("");
}

export class Vault {
  private dek: CryptoKey | null = null;
  private dekRaw: Uint8Array | null = null;
  private mem = new Map<string, Memory>();
  /** Optional on-device embedder. Without it (or if it fails) search is keyword-only, and says so. */
  embedder: Embedder | null = null;
  lastSearchMode: "hybrid" | "keyword" = "keyword";

  get unlocked(): boolean {
    return this.dek !== null;
  }

  static async exists(): Promise<boolean> {
    return (await store.getEnvelope()) !== undefined;
  }

  /** First-time setup. Returns the recovery key, which must be shown to the user exactly once. */
  async setup(passphrase: string, iterations?: number): Promise<string> {
    if (await Vault.exists()) throw new Error("A vault already exists on this device");
    const v = await createVault(passphrase, iterations);
    await store.putEnvelope(v.envelope);
    this.dek = v.dek;
    this.dekRaw = v.dekRaw;
    this.mem.clear();
    return v.recoveryKey;
  }

  async unlock(passphrase: string): Promise<void> {
    const env = await store.getEnvelope();
    if (!env) throw new Error("No vault on this device");
    try {
      ({ dek: this.dek, dekRaw: this.dekRaw } = await unlockWithPassphrase(env, passphrase));
    } catch {
      throw new Error("Wrong passphrase");
    }
    await this.load();
  }

  async recover(recoveryKey: string, newPassphrase: string): Promise<void> {
    const env = await store.getEnvelope();
    if (!env) throw new Error("No vault on this device");
    try {
      ({ dek: this.dek, dekRaw: this.dekRaw } = await unlockWithRecovery(env, recoveryKey));
    } catch {
      throw new Error("Wrong recovery key");
    }
    await store.putEnvelope(await changePassphrase(env, this.dekRaw!, newPassphrase));
    await this.load();
  }

  /** Restore an unlocked session from a raw key kept in memory-only session storage. */
  async resume(dekRaw: Uint8Array): Promise<void> {
    const { importDek } = await import("./crypto");
    this.dek = await importDek(dekRaw);
    this.dekRaw = dekRaw;
    await this.load();
  }

  exportSessionKey(): Uint8Array | null {
    return this.dekRaw;
  }

  async changePassphrase(current: string, next: string): Promise<void> {
    const env = await store.getEnvelope();
    if (!env) throw new Error("No vault on this device");
    let raw: Uint8Array;
    try {
      raw = (await unlockWithPassphrase(env, current)).dekRaw;
    } catch {
      throw new Error("Current passphrase is wrong");
    }
    await store.putEnvelope(await changePassphrase(env, raw, next));
  }

  lock(): void {
    this.dek = null;
    this.dekRaw = null;
    this.mem.clear();
  }

  private need(): CryptoKey {
    if (!this.dek) throw new Error("Vault is locked");
    return this.dek;
  }

  private async load(): Promise<void> {
    const dek = this.need();
    this.mem.clear();
    for (const r of await store.all()) this.mem.set(r.id, await openJson<Memory>(dek, r.sealed));
  }

  private async save(m: Memory): Promise<void> {
    this.mem.set(m.id, m);
    await store.put({ id: m.id, sealed: await sealJson(this.need(), m) });
  }

  list(filter?: { status?: Status; category?: Category }): Memory[] {
    return [...this.mem.values()]
      .filter((m) => (!filter?.status || m.status === filter.status) && (!filter?.category || m.category === filter.category))
      .sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }

  get(id: string): Memory | undefined {
    return this.mem.get(id);
  }

  /**
   * Capture a message the user sent to an AI. Each memorable sentence becomes a memory.
   * Returns the memories created (active or pending).
   */
  async ingestMessage(text: string, source: Memory["source"], now = new Date()): Promise<Memory[]> {
    this.need();
    const created: Memory[] = [];
    const candidates = source.kind === "manual" ? [text.trim()] : sentences(text);
    for (const raw of candidates) {
      const flags = screen(raw);
      if (!flags.length && source.kind !== "manual" && !isMemorable(raw)) continue;
      const { text: clean, kinds } = redact(raw);
      const active = this.list({ status: "active" });
      if (active.some((m) => jaccard(m.text, clean) >= DUPLICATE)) continue;
      const category = categorize(clean);
      const m: Memory = {
        id: crypto.randomUUID(),
        text: clean,
        category,
        status: flags.length ? "pending" : "active",
        source,
        createdAt: now.toISOString(),
        redactions: kinds,
        flags,
        slot: slotOf(clean),
      };
      if (m.status === "active") {
        const older = active
          .filter((o) => !o.updatedBy)
          .map((o) => ({ o, s: m.slot && o.slot === m.slot ? 1 : o.category === category && category !== "other" ? jaccard(o.text, clean) : 0 }))
          .filter((x) => x.s >= SAME_SUBJECT)
          .sort((a, b) => b.s - a.s || b.o.createdAt.localeCompare(a.o.createdAt))[0];
        if (older) {
          m.updates = older.o.id;
          await this.save({ ...older.o, updatedBy: m.id });
        }
      }
      await this.save(m);
      created.push(m);
    }
    if (created.length) await this.embedMissing(created);
    return created;
  }

  /** Embed memories that have no vector yet (new ones, or ones stored before the model was available). */
  async embedMissing(only?: Memory[]): Promise<number> {
    if (!this.embedder) return 0;
    const todo = (only ?? [...this.mem.values()]).filter((m) => !m.vec);
    for (let i = 0; i < todo.length; i += 32) {
      const batch = todo.slice(i, i + 32);
      try {
        const vecs = await this.embedder(batch.map((m) => m.text));
        for (let j = 0; j < batch.length; j++) {
          const cur = this.mem.get(batch[j].id);
          if (cur) await this.save({ ...cur, vec: vecs[j] });
        }
      } catch {
        return i; // model unavailable: memories stay searchable by keyword and get embedded later
      }
    }
    return todo.length;
  }

  /** Relevant, servable memories for a prompt. Pending and retired memories are never returned. */
  async search(query: string, topK = 6, lexicalWeight = LEXICAL_WEIGHT): Promise<Memory[]> {
    const active = this.list({ status: "active" });
    if (!active.length) return [];
    const lex = new Map(
      new BM25(active.map((m) => ({ id: m.id, text: `${m.category} ${m.text}` }))).search(query, POOL).map((h) => [h.id, h.score]),
    );
    let dense = new Map<string, number>();
    this.lastSearchMode = "keyword";
    if (this.embedder) {
      try {
        const [qv] = await this.embedder([query]);
        dense = new Map(
          active.filter((m) => m.vec).map((m) => [m.id, cosine(qv, m.vec!)] as [string, number])
            .sort((a, b) => b[1] - a[1]).slice(0, POOL),
        );
        this.lastSearchMode = "hybrid";
      } catch {
        dense = new Map();
      }
    }
    const ln = lex.size ? minmax(lex) : new Map<string, number>();
    const dn = dense.size ? minmax(dense) : new Map<string, number>();
    const w = dense.size ? lexicalWeight : 1;
    const ids = new Set([...ln.keys(), ...dn.keys()]);
    const ranked = [...ids]
      .map((id) => ({ id, s: w * (ln.get(id) ?? 0) + (1 - w) * (dn.get(id) ?? 0) }))
      .sort((a, b) => b.s - a.s)
      .slice(0, topK);
    const out = ranked.map((r) => this.mem.get(r.id)!);
    // If a hit has a newer version, include it, so the reader sees the change.
    for (const m of [...out]) {
      const newer = m.updatedBy ? this.mem.get(m.updatedBy) : undefined;
      if (newer && newer.status === "active" && !out.includes(newer)) out.push(newer);
    }
    return out;
  }

  /** Context block for an AI prompt: oldest first, dated, later entries are current. */
  async context(query: string, topK = 6): Promise<string> {
    const ms = (await this.search(query, topK)).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
    if (!ms.length) return "";
    const lines = ms.map((m) => `- [${m.createdAt.slice(0, 10)}] ${m.text}`);
    return [
      "Context from my personal memory (AegisMem). Oldest first; if two entries disagree, the later one is current:",
      ...lines,
    ].join("\n");
  }

  async approve(id: string): Promise<void> {
    const m = this.mem.get(id);
    if (m?.status === "pending") await this.save({ ...m, status: "active" });
  }

  async edit(id: string, text: string): Promise<Memory> {
    const m = this.mem.get(id);
    if (!m) throw new Error("Not found");
    const { text: clean, kinds } = redact(text.trim());
    const next: Memory = { ...m, text: clean, category: categorize(clean), redactions: kinds, slot: slotOf(clean), vec: undefined };
    await this.save(next);
    await this.embedMissing([next]);
    return this.mem.get(next.id)!;
  }

  async setCategory(id: string, category: Category): Promise<void> {
    const m = this.mem.get(id);
    if (m) await this.save({ ...m, category });
  }

  /** Permanently erase. The record is removed from storage, not just hidden. */
  async forget(id: string, now = new Date()): Promise<Receipt> {
    this.need();
    const m = this.mem.get(id);
    this.mem.delete(id);
    await store.delete(id);
    for (const linkedId of [m?.updates, m?.updatedBy]) {
      const o = linkedId ? this.mem.get(linkedId) : undefined;
      if (o) await this.save({ ...o, updates: o.updates === id ? undefined : o.updates, updatedBy: o.updatedBy === id ? undefined : o.updatedBy });
    }
    const erasedAt = now.toISOString();
    return { memoryId: id, erasedAt, digest: await sha256(`${id}|${erasedAt}|erased`), verified: !(await store.has(id)) };
  }

  async forgetAll(): Promise<number> {
    const n = this.mem.size;
    await store.clear();
    this.mem.clear();
    return n;
  }

  /** Plaintext export, only on the user's explicit request. */
  exportJson(): string {
    const memories = this.list().map(({ vec: _vec, ...m }) => m);
    return JSON.stringify({ exportedAt: new Date().toISOString(), memories }, null, 2);
  }
}
