/**
 * "Find that chat" benchmark on LongMemEval-S (MIT; Wu et al., ICLR 2025).
 *
 * Library: every distinct chat session in the split's histories (about 10k conversations, about 100M
 * characters, a very heavy user). Queries: the benchmark's natural-language questions (abstention
 * excluded). Gold: the session(s) that contain the answer. The search runs on the product's own code
 * (chunksOf → SearchIndex, int8 vectors, all-MiniLM-L6-v2 on-device model).
 *
 *   hit@k   a gold conversation is in the top k
 *   mrr     mean reciprocal rank of the first gold conversation (rank > 50 counts as 0)
 * 95% bootstrap CIs over questions. Dev split for tuning; the test split is run once.
 *
 *   SPLIT=dev  node eval/run.mjs            (all systems + lexical-weight sweep)
 *   SPLIT=test node eval/run.mjs            (shipped configuration vs baselines)
 */
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";
import { ARCTIC_XS, createEmbedder, MINILM } from "../src/core/embed";
import { quantize, SearchIndex, DEFAULT_LEXICAL_WEIGHT } from "../src/core/index";
import { chunksOf } from "../src/core/library";
import type { Conversation } from "../src/core/types";

type Turn = { role: string; content: string };
type Q = { question_id: string; question_type: string; question: string; haystack_session_ids: string[]; haystack_dates: string[]; haystack_sessions: Turn[][]; answer_session_ids: string[] };

const SPLIT = process.env.SPLIT === "test" ? "test" : "dev";
const data: Q[] = JSON.parse(readFileSync(resolve(homedir(), ".cache/aegis-bench/longmemeval_s_cleaned.json"), "utf8"));
const qs = data.filter((q) => !q.question_id.endsWith("_abs") && (createHash("sha256").update(q.question_id).digest()[0] % 2 === 0) === (SPLIT === "dev"));

// ---- library of conversations
const convs = new Map<string, Conversation>();
for (const q of qs) {
  q.haystack_session_ids.forEach((sid, i) => {
    if (convs.has(sid)) return;
    const d = q.haystack_dates[i];
    const at = new Date(d.replace(/ \(\w+\)/, "").replace(/\//g, "-") + "Z").toISOString();
    const messages = q.haystack_sessions[i].filter((t) => t.content?.trim()).map((t) => ({ role: (t.role === "user" ? "user" : "assistant") as "user" | "assistant", text: t.content }));
    // No titles: LongMemEval sessions have none (real exports do, which only helps).
    convs.set(sid, { id: sid, platform: "chatgpt", nativeId: sid, title: "", createdAt: at, updatedAt: at, messages, source: "import" });
  });
}
const chunks = [...convs.values()].flatMap((c) => chunksOf(c));
console.log(`${SPLIT}: ${qs.length} questions, ${convs.size} conversations, ${chunks.length} chunks`);

// ---- embeddings, cached on disk (sha1(text) -> int8[384])
const SPEC = process.env.MODEL === "minilm" ? MINILM : ARCTIC_XS; // default: shipped model
const MODEL_ROOT = SPEC === MINILM ? resolve("eval/.out/models") + "/" : resolve("static/models") + "/";
const CACHE = resolve(SPEC === MINILM ? "eval/.out/emb-cache.bin" : `eval/.out/emb-cache-${SPEC.name}.bin`);
mkdirSync(resolve("eval/.out"), { recursive: true });
const cache = new Map<string, Int8Array>();
if (existsSync(CACHE)) {
  const buf = readFileSync(CACHE);
  for (let o = 0; o + 404 <= buf.length; o += 404) cache.set(buf.subarray(o, o + 20).toString("hex"), new Int8Array(buf.buffer.slice(buf.byteOffset + o + 20, buf.byteOffset + o + 404)));
}
const key = (t: string) => createHash("sha1").update(t).digest("hex");
const qkey = (t: string) => key(`\u0000query\u0000${t}`); // queries may carry a model-specific prefix
const embed = await createEmbedder({ modelRoot: MODEL_ROOT, device: "cpu", spec: SPEC });
for (const q of qs) if (!cache.has(qkey(q.question))) cache.set(qkey(q.question), quantize((await embed([q.question], true))[0]));
const todo = [...new Set(chunks.map((c) => c.text))].filter((t) => !cache.has(key(t)));
const t0 = Date.now();
for (let i = 0; i < todo.length; i += 64) {
  const batch = todo.slice(i, i + 64);
  const vs = await embed(batch);
  batch.forEach((t, j) => cache.set(key(t), quantize(vs[j])));
  if ((i / 64) % 100 === 0) console.log(`  embedded ${i + batch.length}/${todo.length} (${((Date.now() - t0) / 60000).toFixed(1)} min)`);
}
if (todo.length) {
  const out = Buffer.alloc(cache.size * 404);
  let o = 0;
  for (const [k, v] of cache) {
    Buffer.from(k, "hex").copy(out, o);
    Buffer.from(v.buffer, v.byteOffset, 384).copy(out, o + 20);
    o += 404;
  }
  writeFileSync(CACHE, out);
}

const index = new SearchIndex();
const tIdx = Date.now();
index.add(chunks.map((c) => ({ ...c, vec: cache.get(key(c.text)) })));
console.log(`  indexed in ${((Date.now() - tIdx) / 1000).toFixed(1)} s`);

// ---- evaluate
function ci(xs: number[]) {
  const n = xs.length;
  const mean = xs.reduce((a, b) => a + b, 0) / n;
  let seed = 11;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const ms: number[] = [];
  for (let b = 0; b < 2000; b++) {
    let s = 0;
    for (let i = 0; i < n; i++) s += xs[Math.floor(rnd() * n)];
    ms.push(s / n);
  }
  ms.sort((a, b) => a - b);
  return { mean: +mean.toFixed(4), lo: +ms[50].toFixed(4), hi: +ms[1949].toFixed(4), n };
}

type Sys = { name: string; w: number; dense: boolean; extra?: Record<string, unknown> };
const EXP = process.env.EXP;
const systems: Sys[] = EXP === "grid"
  ? [
      { name: "kw", w: 1, dense: false },
      { name: "kw k1=0.9 b=0.4", w: 1, dense: false, extra: { k1: 0.9, b: 0.4 } },
      { name: "kw k1=1.5 b=0.75", w: 1, dense: false, extra: { k1: 1.5, b: 0.75 } },
      { name: "kw k1=1.2 b=0.5", w: 1, dense: false, extra: { b: 0.5 } },
      { name: "kw top3", w: 1, dense: false, extra: { aggregate: "top3" } },
      { name: "kw max", w: 1, dense: false, extra: { aggregate: "max" } },
      { name: "kw user1.3", w: 1, dense: false, extra: { roleWeight: { user: 1.3 } } },
      { name: "kw user1.6", w: 1, dense: false, extra: { roleWeight: { user: 1.6 } } },
      { name: "hy0.8 floor", w: 0.8, dense: true },
      { name: "hy0.8 nofloor", w: 0.8, dense: true, extra: { minDense: -1 } },
      { name: "hy0.8 user1.3", w: 0.8, dense: true, extra: { roleWeight: { user: 1.3 } } },
      { name: "hy0.8 top3", w: 0.8, dense: true, extra: { aggregate: "top3" } },
    ]
  : SPLIT === "dev"
  ? [{ name: "keyword", w: 1, dense: false }, { name: "meaning", w: 0, dense: true },
     ...[0.3, 0.5, 0.6, 0.7, 0.8, 0.9].map((w) => ({ name: `hybrid@${w}`, w, dense: true }))]
  : [{ name: "keyword", w: 1, dense: false }, { name: "meaning", w: 0, dense: true }, { name: `hybrid@${DEFAULT_LEXICAL_WEIGHT}`, w: DEFAULT_LEXICAL_WEIGHT, dense: true }];

const rows: Record<string, { type: string; hit1: number; hit5: number; hit10: number; rr: number }[]> = {};
const lat: number[] = [];
for (const s of systems) {
  rows[s.name] = [];
  for (const q of qs) {
    const gold = new Set(q.answer_session_ids);
    const t = performance.now();
    const hits = index.search(q.question, s.dense ? cache.get(qkey(q.question))! : null, { limit: 50, lexicalWeight: s.w, ...(s.extra ?? {}) });
    if (s.name.startsWith("hybrid@0.7")) lat.push(performance.now() - t);
    const rank = hits.findIndex((h) => gold.has(h.convId));
    rows[s.name].push({ type: q.question_type, hit1: +(rank === 0), hit5: +(rank >= 0 && rank < 5), hit10: +(rank >= 0 && rank < 10), rr: rank >= 0 ? 1 / (rank + 1) : 0 });
  }
}
const summary: Record<string, unknown> = {
  dataset: `LongMemEval-S cleaned (MIT), ${SPLIT} split, conversation retrieval`,
  model: SPEC.name,
  questions: qs.length, conversations: convs.size, chunks: chunks.length,
  latency_ms_hybrid: lat.length ? { p50: +lat.sort((a, b) => a - b)[Math.floor(lat.length / 2)].toFixed(1), p95: +lat[Math.floor(lat.length * 0.95)].toFixed(1) } : undefined,
  systems: {} as Record<string, unknown>,
};
for (const [name, rs] of Object.entries(rows)) {
  (summary.systems as Record<string, unknown>)[name] = {
    hit1: ci(rs.map((r) => r.hit1)), hit5: ci(rs.map((r) => r.hit5)), hit10: ci(rs.map((r) => r.hit10)), mrr: ci(rs.map((r) => r.rr)),
    by_type: Object.fromEntries([...new Set(rs.map((r) => r.type))].sort().map((t) => [t, +ci(rs.filter((r) => r.type === t).map((r) => r.hit5)).mean.toFixed(3)])),
  };
}
const hy = EXP ? undefined : rows[`hybrid@${DEFAULT_LEXICAL_WEIGHT}`];
if (hy) {
  summary.hybrid_minus_keyword_hit1 = ci(hy.map((r, i) => r.hit1 - rows.keyword[i].hit1));
  summary.hybrid_minus_meaning_hit1 = ci(hy.map((r, i) => r.hit1 - rows.meaning[i].hit1));
}
writeFileSync(EXP ? `eval/.out/exp-${EXP}-${SPLIT}-${SPEC.name}.json` : `eval/conversations-${SPLIT}-${SPEC.name}.json`, JSON.stringify(summary, null, 2));
for (const [name, v] of Object.entries(summary.systems as Record<string, { hit1: { mean: number }; hit5: { mean: number }; mrr: { mean: number } }>)) {
  console.log(`  ${name.padEnd(12)} hit@1 ${(v.hit1.mean * 100).toFixed(1)}  hit@5 ${(v.hit5.mean * 100).toFixed(1)}  MRR ${v.mrr.mean.toFixed(3)}`);
}
console.log("  latency", JSON.stringify(summary.latency_ms_hybrid));
