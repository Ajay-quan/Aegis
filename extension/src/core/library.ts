/**
 * The Recall library: encrypted conversation store + in-memory hybrid index + on-device embedder.
 * Decrypted conversations live only in this object's memory.
 */
import { b64, openJson, sealJson, unb64, PBKDF2_ITERATIONS } from "./crypto";
import { db } from "./db";
import { chunkText, quantize, SearchIndex, type ChunkInput, type Hit, type SearchOptions } from "./index";
import { changePassphrase, importDek, newDeviceKey, newPassphraseKey, unlockWithPassphrase, unlockWithRecovery, type KeyMode } from "./keys";
import { maskSecrets } from "./redact";
import { PLATFORMS, type Conversation, type Platform } from "./types";
import type { Embedder } from "./vector";

export const EMBED_MODEL = "all-MiniLM-L6-v2";

interface Stored {
  conv: Conversation;
  model?: string;
  vecs?: string[]; // base64 int8, one per chunk (same order as chunksOf)
}

export interface Result extends Hit {
  title: string;
  platform: Platform;
  updatedAt: string;
  url: string;
}

export interface Progress {
  done: number;
  total: number;
  phase: "embedding" | "saving";
}

export interface UpsertReport {
  added: number;
  updated: number;
  unchanged: number;
}

export function chunksOf(c: Conversation): Omit<ChunkInput, "vec">[] {
  const convAt = Date.parse(c.updatedAt) || 0;
  const out: Omit<ChunkInput, "vec">[] = [];
  if (c.title.trim()) out.push({ convId: c.id, platform: c.platform, role: "title", msgIndex: -1, text: c.title.trim(), at: convAt });
  c.messages.forEach((m, i) => {
    const at = (m.at && Date.parse(m.at)) || convAt;
    for (const t of chunkText(m.text)) out.push({ convId: c.id, platform: c.platform, role: m.role, msgIndex: i, text: t, at });
  });
  return out;
}

function fingerprint(c: Conversation): string {
  const last = c.messages[c.messages.length - 1];
  return `${c.title}|${c.messages.length}|${last?.text.length ?? 0}|${last?.text.slice(-64) ?? ""}`;
}

export class Library {
  private key: CryptoKey | null = null;
  private rawKey: Uint8Array | null = null; // passphrase mode only, for session resume
  mode: KeyMode | null = null;
  private convs = new Map<string, Stored>();
  readonly index = new SearchIndex();
  embedder: Embedder | null = null;
  maskSecrets = true;
  lastSearchMode: "hybrid" | "keyword" = "keyword";

  get unlocked(): boolean {
    return this.key !== null;
  }

  /** Returns the key mode if a library exists on this device; opens device-mode libraries directly. */
  async init(): Promise<KeyMode | null> {
    const rec = await db.getKey();
    if (!rec) return (this.mode = null);
    this.mode = rec.mode;
    if (rec.mode === "device" && !this.key) {
      this.key = rec.key;
      await this.load();
    }
    return this.mode;
  }

  async setupDevice(): Promise<void> {
    if (await db.getKey()) throw new Error("Already set up");
    this.key = await newDeviceKey();
    await db.putKey({ mode: "device", key: this.key });
    this.mode = "device";
  }

  async setupPassphrase(passphrase: string, iterations = PBKDF2_ITERATIONS): Promise<string> {
    if (await db.getKey()) throw new Error("Already set up");
    const v = await newPassphraseKey(passphrase, iterations);
    await db.putKey({ mode: "passphrase", envelope: v.envelope });
    this.key = v.dek;
    this.rawKey = v.dekRaw;
    this.mode = "passphrase";
    return v.recoveryKey;
  }

  async unlock(passphrase: string): Promise<void> {
    const rec = await db.getKey();
    if (rec?.mode !== "passphrase") throw new Error("No passphrase-protected library");
    try {
      ({ dek: this.key, dekRaw: this.rawKey } = await unlockWithPassphrase(rec.envelope, passphrase));
    } catch {
      throw new Error("Wrong passphrase");
    }
    await this.load();
  }

  async recover(recoveryKey: string, newPassphrase: string): Promise<void> {
    const rec = await db.getKey();
    if (rec?.mode !== "passphrase") throw new Error("No passphrase-protected library");
    try {
      ({ dek: this.key, dekRaw: this.rawKey } = await unlockWithRecovery(rec.envelope, recoveryKey));
    } catch {
      throw new Error("Wrong recovery key");
    }
    await db.putKey({ mode: "passphrase", envelope: await changePassphrase(rec.envelope, this.rawKey!, newPassphrase) });
    await this.load();
  }

  async changePassphrase(current: string, next: string): Promise<void> {
    const rec = await db.getKey();
    if (rec?.mode !== "passphrase") throw new Error("Library is not passphrase-protected");
    let raw: Uint8Array;
    try {
      raw = (await unlockWithPassphrase(rec.envelope, current)).dekRaw;
    } catch {
      throw new Error("Current passphrase is wrong");
    }
    await db.putKey({ mode: "passphrase", envelope: await changePassphrase(rec.envelope, raw, next) });
  }

  async resume(raw: Uint8Array): Promise<void> {
    this.key = await importDek(raw);
    this.rawKey = raw;
    await this.load();
  }

  sessionKey(): Uint8Array | null {
    return this.mode === "passphrase" ? this.rawKey : null;
  }

  lock(): void {
    if (this.mode !== "passphrase") return; // device mode has nothing to lock
    this.key = null;
    this.rawKey = null;
    this.convs.clear();
    this.index.clear();
  }

  /** Re-encrypt everything under a new key mode. Returns a recovery key when switching to passphrase. */
  async switchMode(to: KeyMode, passphrase?: string): Promise<string | undefined> {
    this.need();
    if (to === this.mode) return;
    let recovery: string | undefined;
    if (to === "device") {
      this.key = await newDeviceKey();
      this.rawKey = null;
      await this.resealAll();
      await db.putKey({ mode: "device", key: this.key });
    } else {
      if (!passphrase) throw new Error("Passphrase required");
      const v = await newPassphraseKey(passphrase);
      this.key = v.dek;
      this.rawKey = v.dekRaw;
      await this.resealAll();
      await db.putKey({ mode: "passphrase", envelope: v.envelope });
      recovery = v.recoveryKey;
    }
    this.mode = to;
    return recovery;
  }

  private async resealAll(): Promise<void> {
    const rs = [];
    for (const [id, s] of this.convs) rs.push({ id, sealed: await sealJson(this.need(), s) });
    await db.putMany(rs);
  }

  private need(): CryptoKey {
    if (!this.key) throw new Error("Library is locked");
    return this.key;
  }

  private async load(): Promise<void> {
    const key = this.need();
    this.convs.clear();
    this.index.clear();
    for (const r of await db.all()) {
      const s = await openJson<Stored>(key, r.sealed);
      this.convs.set(r.id, s);
      this.indexConv(s);
    }
  }

  private indexConv(s: Stored): void {
    const cs = chunksOf(s.conv);
    const vecs = s.model === EMBED_MODEL && s.vecs?.length === cs.length ? s.vecs : undefined;
    this.index.add(cs.map((c, i) => ({ ...c, vec: vecs ? new Int8Array(unb64(vecs[i]).buffer) : undefined })));
  }

  /** Insert or update conversations. Unchanged ones (same fingerprint) are skipped. */
  async upsert(list: Conversation[], onProgress?: (p: Progress) => void): Promise<UpsertReport> {
    const key = this.need();
    const report: UpsertReport = { added: 0, updated: 0, unchanged: 0 };
    const todo: Stored[] = [];
    for (const raw of list) {
      const conv: Conversation = this.maskSecrets ? { ...raw, title: maskSecrets(raw.title), messages: raw.messages.map((m) => ({ ...m, text: maskSecrets(m.text) })) } : raw;
      const prev = this.convs.get(conv.id);
      if (prev && fingerprint(prev.conv) === fingerprint(conv) && (prev.model === EMBED_MODEL || !this.embedder)) {
        report.unchanged++;
        continue;
      }
      if (prev) report.updated++;
      else report.added++;
      todo.push({ conv });
    }
    await this.embedAll(todo, onProgress);
    for (let i = 0; i < todo.length; i += 50) {
      const batch = todo.slice(i, i + 50);
      await db.putMany(await Promise.all(batch.map(async (s) => ({ id: s.conv.id, sealed: await sealJson(key, s) }))));
      for (const s of batch) {
        this.index.remove(s.conv.id);
        this.convs.set(s.conv.id, s);
        this.indexConv(s);
      }
      onProgress?.({ done: Math.min(i + 50, todo.length), total: todo.length, phase: "saving" });
    }
    return report;
  }

  private async embedAll(todo: Stored[], onProgress?: (p: Progress) => void): Promise<void> {
    if (!this.embedder) return;
    const jobs: { s: Stored; i: number; text: string }[] = [];
    for (const s of todo) {
      s.vecs = [];
      chunksOf(s.conv).forEach((c, i) => jobs.push({ s, i, text: c.text }));
    }
    const B = 32;
    try {
      for (let k = 0; k < jobs.length; k += B) {
        const batch = jobs.slice(k, k + B);
        const vs = await this.embedder(batch.map((j) => j.text));
        batch.forEach((j, n) => (j.s.vecs![j.i] = b64(new Uint8Array(quantize(vs[n]).buffer))));
        onProgress?.({ done: Math.min(k + B, jobs.length), total: jobs.length, phase: "embedding" });
      }
      for (const s of todo) s.model = EMBED_MODEL;
    } catch {
      for (const s of todo) {
        delete s.vecs;
        delete s.model;
      }
    }
  }

  /** Embed conversations stored without vectors (e.g. saved while the model was unavailable). */
  async embedMissing(onProgress?: (p: Progress) => void): Promise<number> {
    const missing = [...this.convs.values()].filter((s) => s.model !== EMBED_MODEL).map((s): Stored => ({ conv: s.conv }));
    if (!missing.length || !this.embedder) return 0;
    await this.embedAll(missing, onProgress);
    const done = missing.filter((s) => s.model === EMBED_MODEL);
    const key = this.need();
    await db.putMany(await Promise.all(done.map(async (s) => ({ id: s.conv.id, sealed: await sealJson(key, s) }))));
    for (const s of done) {
      this.index.remove(s.conv.id);
      this.convs.set(s.conv.id, s);
      this.indexConv(s);
    }
    return done.length;
  }

  async search(query: string, opts: SearchOptions = {}): Promise<Result[]> {
    this.need();
    if (!query.trim()) return [];
    let qvec: Int8Array | null = null;
    this.lastSearchMode = "keyword";
    if (this.embedder) {
      try {
        qvec = quantize((await this.embedder([query]))[0]);
        this.lastSearchMode = "hybrid";
      } catch {
        qvec = null;
      }
    }
    return this.index.search(query, qvec, opts).map((h) => {
      const c = this.convs.get(h.convId)!.conv;
      return { ...h, title: c.title, platform: c.platform, updatedAt: c.updatedAt, url: urlOf(c) };
    });
  }

  get(id: string): Conversation | undefined {
    return this.convs.get(id)?.conv;
  }

  recent(limit = 50, platform?: Platform): Conversation[] {
    return [...this.convs.values()]
      .map((s) => s.conv)
      .filter((c) => !platform || c.platform === platform)
      .sort((a, b) => b.updatedAt.localeCompare(a.updatedAt))
      .slice(0, limit);
  }

  stats() {
    const by: Record<string, number> = {};
    let messages = 0;
    let embedded = 0;
    for (const s of this.convs.values()) {
      by[s.conv.platform] = (by[s.conv.platform] ?? 0) + 1;
      messages += s.conv.messages.length;
      if (s.model === EMBED_MODEL) embedded++;
    }
    return { conversations: this.convs.size, messages, chunks: this.index.size, embedded, byPlatform: by };
  }

  async remove(id: string): Promise<boolean> {
    this.need();
    this.convs.delete(id);
    this.index.remove(id);
    await db.delete(id);
    return (await db.get(id)) === undefined;
  }

  async removeAll(): Promise<number> {
    const n = this.convs.size;
    await db.clearConvs();
    this.convs.clear();
    this.index.clear();
    return n;
  }

  allConversations(): Conversation[] {
    return [...this.convs.values()].map((s) => s.conv);
  }
}

export function urlOf(c: Conversation): string {
  return PLATFORMS[c.platform].url(c.nativeId);
}
