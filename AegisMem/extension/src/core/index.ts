/**
 * In-memory search index over decrypted chunks (rebuilt from the encrypted store on unlock).
 *
 *   lexical   incremental inverted index, BM25 (k1 1.2, b 0.75)
 *   dense     384-d int8-quantized unit vectors, exact dot product (no ANN approximation)
 *   fusion    min-max normalise each over its candidate pool, then (1 - w) * dense + w * lexical
 *   ranking   conversations scored by their best chunk (MaxP) plus a small bonus per extra matching chunk
 */
import { tokens } from "./search";
import type { Platform, Role } from "./types";

export interface ChunkInput {
  convId: string;
  platform: Platform;
  role: Role | "title";
  msgIndex: number; // -1 for the title chunk
  text: string;
  at: number; // epoch ms (message time, else conversation time)
  vec?: Int8Array;
}

interface Chunk extends ChunkInput {
  len: number;
}

export interface SearchOptions {
  platforms?: Platform[];
  role?: Role;
  from?: number; // epoch ms
  to?: number;
  limit?: number; // conversations
  lexicalWeight?: number;
  minDense?: number; // cosine floor for meaning-only candidates (unrelated text scores ~0–0.2)
  relativeCutoff?: number; // drop conversations scoring below this fraction of the best one
  roleWeight?: Partial<Record<Role | "title", number>>; // multiply fused chunk scores by role
  aggregate?: "max" | "maxBonus" | "top3"; // chunk scores -> conversation score
  k1?: number;
  b?: number;
}

export interface Hit {
  convId: string;
  score: number;
  best: { msgIndex: number; role: Role | "title"; text: string; snippet: Snippet };
  matches: number;
}

export interface Snippet {
  text: string;
  ranges: [number, number][]; // highlight ranges in `text`
}

export const DEFAULT_LEXICAL_WEIGHT = 0.7;
export const DEFAULT_MIN_DENSE = 0.25;
export const DEFAULT_RELATIVE_CUTOFF = 0.3;
const K1 = 1.2;
const B = 0.75;
const POOL = 200;

export function quantize(v: number[] | Float32Array): Int8Array {
  const q = new Int8Array(v.length);
  for (let i = 0; i < v.length; i++) q[i] = Math.max(-127, Math.min(127, Math.round(v[i] * 127)));
  return q;
}

/** The k largest [id, score] pairs, without sorting everything (min-heap of size k). */
export function topK(entries: Iterable<[number, number]>, k: number): [number, number][] {
  const heap: [number, number][] = [];
  const up = (i: number) => {
    while (i > 0) {
      const p = (i - 1) >> 1;
      if (heap[p][1] <= heap[i][1]) break;
      [heap[p], heap[i]] = [heap[i], heap[p]];
      i = p;
    }
  };
  const down = (i: number) => {
    for (;;) {
      const l = 2 * i + 1;
      const r = l + 1;
      let m = i;
      if (l < heap.length && heap[l][1] < heap[m][1]) m = l;
      if (r < heap.length && heap[r][1] < heap[m][1]) m = r;
      if (m === i) break;
      [heap[m], heap[i]] = [heap[i], heap[m]];
      i = m;
    }
  };
  for (const e of entries) {
    if (heap.length < k) {
      heap.push(e);
      up(heap.length - 1);
    } else if (e[1] > heap[0][1]) {
      heap[0] = e;
      down(0);
    }
  }
  return heap.sort((a, b) => b[1] - a[1]);
}

function minmax(m: Map<number, number>): Map<number, number> {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of m.values()) {
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  const out = new Map<number, number>();
  for (const [k, v] of m) out.set(k, hi > lo ? (v - lo) / (hi - lo) : 1);
  return out;
}

export function snippet(text: string, query: string, width = 240): Snippet {
  const terms = [...new Set(tokens(query))].filter((t) => t.length > 1);
  const lower = text.toLowerCase();
  let first = -1;
  for (const t of terms) {
    const re = new RegExp(`\\b${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "i");
    const m = re.exec(lower);
    if (m && (first < 0 || m.index < first)) first = m.index;
  }
  let start = first < 0 ? 0 : Math.max(0, first - Math.floor(width / 3));
  if (start > 0) {
    const sp = text.indexOf(" ", start);
    start = sp >= 0 && sp - start < 20 ? sp + 1 : start;
  }
  const end = Math.min(text.length, start + width);
  let s = text.slice(start, end).replace(/\s+/g, " ");
  const prefix = start > 0 ? "…" : "";
  const suffix = end < text.length ? "…" : "";
  s = prefix + s + suffix;
  const ranges: [number, number][] = [];
  const sl = s.toLowerCase();
  for (const t of terms) {
    const re = new RegExp(`\\b${t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\w*`, "gi");
    for (const m of sl.matchAll(re)) ranges.push([m.index!, m.index! + m[0].length]);
  }
  ranges.sort((a, b) => a[0] - b[0]);
  const merged: [number, number][] = [];
  for (const r of ranges) {
    const last = merged[merged.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else merged.push([...r]);
  }
  return { text: s, ranges: merged };
}

function aggregate(v: { best: number; n: number; top: number[] }, how: "max" | "maxBonus" | "top3"): number {
  if (how === "max") return v.best;
  if (how === "top3") {
    const t = v.top.sort((a, b) => b - a);
    return t[0] + 0.5 * (t[1] ?? 0) + 0.25 * (t[2] ?? 0);
  }
  return v.best + 0.02 * Math.min(v.n - 1, 5);
}

export class SearchIndex {
  private chunks: (Chunk | undefined)[] = [];
  private byConv = new Map<string, number[]>();
  private postings = new Map<string, Map<number, number>>(); // term -> chunk -> tf
  private totalLen = 0;
  private live = 0;
  // All vectors in one contiguous buffer (row i = chunk i); hasVec marks rows that are set.
  private dim = 0;
  private vecs = new Int8Array(0);
  private hasVec = new Uint8Array(0);

  get size(): number {
    return this.live;
  }

  get conversations(): number {
    return this.byConv.size;
  }

  add(cs: ChunkInput[]): void {
    for (const c of cs) {
      const id = this.chunks.length;
      const ts = tokens(c.text);
      const tf = new Map<string, number>();
      for (const t of ts) tf.set(t, (tf.get(t) ?? 0) + 1);
      for (const [t, f] of tf) {
        let p = this.postings.get(t);
        if (!p) this.postings.set(t, (p = new Map()));
        p.set(id, f);
      }
      this.chunks.push({ ...c, vec: undefined, len: ts.length });
      this.storeVec(id, c.vec);
      this.totalLen += ts.length;
      this.live++;
      const list = this.byConv.get(c.convId);
      if (list) list.push(id);
      else this.byConv.set(c.convId, [id]);
    }
  }

  private storeVec(id: number, v?: Int8Array): void {
    const cap = this.hasVec.length;
    if (id >= cap) {
      const n = Math.max(1024, cap * 2, id + 1);
      const hv = new Uint8Array(n);
      hv.set(this.hasVec);
      this.hasVec = hv;
      if (this.dim) {
        const vv = new Int8Array(n * this.dim);
        vv.set(this.vecs);
        this.vecs = vv;
      }
    }
    if (!v) return;
    if (!this.dim) {
      this.dim = v.length;
      this.vecs = new Int8Array(this.hasVec.length * this.dim);
    }
    this.vecs.set(v, id * this.dim);
    this.hasVec[id] = 1;
  }

  remove(convId: string): void {
    for (const id of this.byConv.get(convId) ?? []) {
      const c = this.chunks[id];
      if (!c) continue;
      for (const t of new Set(tokens(c.text))) {
        const p = this.postings.get(t);
        p?.delete(id);
        if (p && !p.size) this.postings.delete(t);
      }
      this.totalLen -= c.len;
      this.live--;
      this.chunks[id] = undefined;
      this.hasVec[id] = 0;
    }
    this.byConv.delete(convId);
  }

  clear(): void {
    this.chunks = [];
    this.dim = 0;
    this.vecs = new Int8Array(0);
    this.hasVec = new Uint8Array(0);
    this.byConv.clear();
    this.postings.clear();
    this.totalLen = 0;
    this.live = 0;
  }

  private firstMessageChunk(convId: string): number | undefined {
    return this.byConv.get(convId)?.find((id) => this.chunks[id]?.role !== "title");
  }

  private passes(c: Chunk, o: SearchOptions): boolean {
    if (o.platforms?.length && !o.platforms.includes(c.platform)) return false;
    if (o.role && c.role !== o.role) return false;
    if (o.from !== undefined && c.at < o.from) return false;
    if (o.to !== undefined && c.at > o.to) return false;
    return true;
  }

  search(query: string, qvec: Int8Array | null, o: SearchOptions = {}): Hit[] {
    const terms = [...new Set(tokens(query))];
    const n = this.live || 1;
    const avg = this.totalLen / n || 1;
    const lex = new Map<number, number>();
    for (const t of terms) {
      const p = this.postings.get(t);
      if (!p) continue;
      const idf = Math.log(1 + (n - p.size + 0.5) / (p.size + 0.5));
      for (const [id, f] of p) {
        const c = this.chunks[id]!;
        if (!this.passes(c, o)) continue;
        const k1 = o.k1 ?? K1;
        const b = o.b ?? B;
        lex.set(id, (lex.get(id) ?? 0) + (idf * f * (k1 + 1)) / (f + k1 * (1 - b + (b * c.len) / avg)));
      }
    }
    const lexTop = new Map(topK(lex, POOL));
    let denseTop = new Map<number, number>();
    if (qvec && this.dim === qvec.length) {
      const filtered = !!(o.platforms?.length || o.role || o.from !== undefined || o.to !== undefined);
      const floor = (o.minDense ?? DEFAULT_MIN_DENSE) * 16129;
      const V = this.vecs;
      const D = this.dim;
      const n = this.chunks.length;
      const self = this;
      function* scores(): Generator<[number, number]> {
        for (let id = 0; id < n; id++) {
          if (!self.hasVec[id]) continue;
          let dot = 0;
          const off = id * D;
          for (let i = 0; i < D; i++) dot += qvec![i] * V[off + i];
          // keep weak semantic matches only if the chunk also matched a keyword
          if (dot < floor && !lex.has(id)) continue;
          if (filtered && !self.passes(self.chunks[id]!, o)) continue;
          yield [id, dot / 16129];
        }
      }
      denseTop = new Map(topK(scores(), POOL));
    }
    const w = denseTop.size ? (lexTop.size ? o.lexicalWeight ?? DEFAULT_LEXICAL_WEIGHT : 0) : 1;
    const ln = minmax(lexTop);
    const dn = minmax(denseTop);
    const fused = new Map<number, number>();
    for (const id of new Set([...ln.keys(), ...dn.keys()])) {
      const rw = o.roleWeight?.[this.chunks[id]!.role] ?? 1;
      fused.set(id, rw * (w * (ln.get(id) ?? 0) + (1 - w) * (dn.get(id) ?? 0)));
    }

    // Rank by the best chunk (title included); show the best *message* chunk as the snippet.
    const convs = new Map<string, { best: number; bestId: number; n: number; msgBest: number; msgId: number; top: number[] }>();
    for (const [id, s] of fused) {
      const c = this.chunks[id]!;
      let cur = convs.get(c.convId);
      if (!cur) convs.set(c.convId, (cur = { best: -1, bestId: id, n: 0, msgBest: -1, msgId: -1, top: [] }));
      cur.n++;
      cur.top.push(s);
      if (s > cur.best) {
        cur.best = s;
        cur.bestId = id;
      }
      if (c.role !== "title" && s > cur.msgBest) {
        cur.msgBest = s;
        cur.msgId = id;
      }
    }
    const ranked = [...convs.entries()]
      .map(([convId, v]) => ({ convId, score: aggregate(v, o.aggregate ?? "maxBonus"), bestId: v.msgId >= 0 ? v.msgId : this.firstMessageChunk(convId) ?? v.bestId, n: v.n }))
      .sort((a, b) => b.score - a.score);
    const floor = (ranked[0]?.score ?? 0) * (o.relativeCutoff ?? DEFAULT_RELATIVE_CUTOFF);
    return ranked
      .filter((h) => h.score >= floor)
      .slice(0, o.limit ?? 20)
      .map((h) => {
        const c = this.chunks[h.bestId]!;
        return { convId: h.convId, score: h.score, matches: h.n, best: { msgIndex: c.msgIndex, role: c.role, text: c.text, snippet: snippet(c.text, query) } };
      });
  }
}

/** Split a message into chunks of at most ~maxChars, preferring sentence boundaries, with overlap. */
export function chunkText(text: string, maxChars = 1000, overlap = 150): string[] {
  const t = text.trim();
  if (t.length <= maxChars) return t ? [t] : [];
  const out: string[] = [];
  let start = 0;
  while (start < t.length) {
    let end = Math.min(t.length, start + maxChars);
    if (end < t.length) {
      const window = t.slice(start, end);
      const cut = Math.max(window.lastIndexOf(". "), window.lastIndexOf("\n"), window.lastIndexOf("? "), window.lastIndexOf("! "));
      if (cut > maxChars * 0.5) end = start + cut + 1;
    }
    out.push(t.slice(start, end).trim());
    if (end >= t.length) break;
    start = Math.max(end - overlap, start + 1);
  }
  return out;
}
