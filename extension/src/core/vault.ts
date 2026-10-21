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
const SAME_SUBJECT = 0.3;

async function sha256(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d), (b) => b.toString(16).padStart(2, "0")).join("");
}

export class Vault {
  private dek: CryptoKey | null = null;
  private dekRaw: Uint8Array | null = null;
  private mem = new Map<string, Memory>();

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
    return created;
  }

  /** Relevant, servable memories for a prompt. Pending and retired memories are never returned. */
  search(query: string, topK = 6): Memory[] {
    const active = this.list({ status: "active" });
    const hits = new BM25(active.map((m) => ({ id: m.id, text: `${m.category} ${m.text}` }))).search(query, topK);
    const out = hits.map((h) => this.mem.get(h.id)!);
    // If a hit has a newer version, include it, so the reader sees the change.
    for (const m of [...out]) {
      const newer = m.updatedBy ? this.mem.get(m.updatedBy) : undefined;
      if (newer && newer.status === "active" && !out.includes(newer)) out.push(newer);
    }
    return out;
  }

  /** Context block for an AI prompt: oldest first, dated, later entries are current. */
  context(query: string, topK = 6): string {
    const ms = this.search(query, topK).sort((a, b) => a.createdAt.localeCompare(b.createdAt));
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
    const next = { ...m, text: clean, category: categorize(clean), redactions: kinds };
    await this.save(next);
    return next;
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
    return JSON.stringify({ exportedAt: new Date().toISOString(), memories: this.list() }, null, 2);
  }
}
