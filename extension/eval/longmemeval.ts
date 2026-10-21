/**
 * Measures the extension's real pipeline (capture filter + redaction + dedupe + hybrid search) on
 * LongMemEval-S (MIT), dev split only (sha256(question_id)[0] even, same rule as bench/answer_eval.py).
 *
 * Per question: every USER turn of the history is captured with Vault.ingestMessage, exactly as the
 * extension does on a site. Then the question is searched.
 *   capture   share of gold evidence turns that produced at least one memory
 *   hit@5     at least one top-5 memory came from a gold evidence turn
 * Systems (identical memories): hybrid (shipped, lexical weight 0.7), keyword-only, meaning-only,
 * plus BM25 over the raw user turns with no capture filter (what filtering costs).
 * Assistant turns are never captured by the extension, so questions whose evidence is only in
 * assistant replies are structural misses; reported per type, not hidden.
 */
import "fake-indexeddb/auto";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";
import { createEmbedder } from "../src/core/embed";
import { BM25 } from "../src/core/search";
import { store } from "../src/core/store";
import { Vault } from "../src/core/vault";

type Turn = { role: string; content: string; has_answer?: boolean };
type Q = { question_id: string; question_type: string; question: string; haystack_dates: string[]; haystack_sessions: Turn[][] };

const data: Q[] = JSON.parse(readFileSync(resolve(homedir(), ".cache/aegis-bench/longmemeval_s_cleaned.json"), "utf8"));
const dev = data.filter((q) => !q.question_id.endsWith("_abs") && createHash("sha256").update(q.question_id).digest()[0] % 2 === 0);
const limit = Number(process.argv[2] ?? dev.length);

function ci(xs: number[]): { mean: number; lo: number; hi: number; n: number } {
  const n = xs.length;
  const mean = xs.reduce((a, b) => a + b, 0) / n;
  let seed = 7;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
  const ms: number[] = [];
  for (let b = 0; b < 2000; b++) {
    let s = 0;
    for (let i = 0; i < n; i++) s += xs[Math.floor(rnd() * n)];
    ms.push(s / n);
  }
  ms.sort((a, b) => a - b);
  return { mean, lo: ms[50], hi: ms[1949], n };
}

const embed = await createEmbedder({ modelRoot: resolve("static/models") + "/", device: "cpu" });
const rows: Record<string, number | string>[] = [];
const t0 = Date.now();
for (const [qi, q] of dev.slice(0, limit).entries()) {
  await store.wipeAll();
  const v = new Vault();
  await v.setup("evaluation passphrase", 1000);
  v.embedder = embed;
  const origin = new Map<string, boolean>(); // memory id -> came from an evidence turn
  const raw: { id: string; text: string; ev: boolean }[] = [];
  let evTurns = 0;
  let evCaptured = 0;
  for (const [si, sess] of q.haystack_sessions.entries()) {
    const when = new Date(q.haystack_dates[si].replace(/ \(\w+\)/, "").replace(/\//g, "-") + "Z");
    for (const [ti, t] of sess.entries()) {
      const ev = !!t.has_answer;
      if (t.role !== "user") {
        if (ev) evTurns++;
        continue;
      }
      if (ev) evTurns++;
      raw.push({ id: `${si}:${ti}`, text: t.content, ev });
      const created = await v.ingestMessage(t.content, { site: "longmemeval", kind: "user_message" }, when);
      for (const m of created) origin.set(m.id, ev);
      if (ev && created.length) evCaptured++;
    }
  }
  const hit = async (w: number | null) => {
    const saved = v.embedder;
    if (w === null) v.embedder = null;
    const ms = await v.search(q.question, 5, w ?? 1);
    v.embedder = saved;
    return ms.some((m) => origin.get(m.id)) ? 1 : 0;
  };
  const rawHits = new BM25(raw).search(q.question, 5).map((h) => raw.find((r) => r.id === h.id)!.ev);
  rows.push({
    type: q.question_type,
    capture: evTurns ? evCaptured / evTurns : 0,
    memories: v.list().length,
    hybrid: await hit(0.7),
    keyword: await hit(null),
    meaning: await hit(0),
    raw_bm25: rawHits.some(Boolean) ? 1 : 0,
  });
  if ((qi + 1) % 10 === 0) console.log(`  ${qi + 1}/${Math.min(limit, dev.length)}  ${((Date.now() - t0) / 60000).toFixed(1)} min`);
}

const systems = ["hybrid", "keyword", "meaning", "raw_bm25"] as const;
const summary: Record<string, unknown> = {
  dataset: "LongMemEval-S cleaned (MIT), dev split, non-abstention",
  questions: rows.length,
  capture: ci(rows.map((r) => r.capture as number)),
  overall: Object.fromEntries(systems.map((s) => [s, ci(rows.map((r) => r[s] as number))])),
  hybrid_minus_keyword: ci(rows.map((r) => (r.hybrid as number) - (r.keyword as number))),
  by_type: {} as Record<string, unknown>,
  mean_memories_per_user: rows.reduce((a, r) => a + (r.memories as number), 0) / rows.length,
};
for (const t of [...new Set(rows.map((r) => r.type as string))].sort()) {
  const rs = rows.filter((r) => r.type === t);
  (summary.by_type as Record<string, unknown>)[t] = {
    n: rs.length,
    capture: ci(rs.map((r) => r.capture as number)).mean,
    ...Object.fromEntries(systems.map((s) => [s, ci(rs.map((r) => r[s] as number)).mean])),
  };
}
writeFileSync("eval/longmemeval-dev.json", JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary, null, 2));
