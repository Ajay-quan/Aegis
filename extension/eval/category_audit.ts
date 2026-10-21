/** Samples categorized memories from real LongMemEval user turns for a manual accuracy audit. */
import "fake-indexeddb/auto";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { resolve } from "node:path";
import { createEmbedder } from "../src/core/embed";
import { store } from "../src/core/store";
import { Vault } from "../src/core/vault";

const data = JSON.parse(readFileSync(resolve(homedir(), ".cache/aegis-bench/longmemeval_s_cleaned.json"), "utf8"));
const embed = await createEmbedder({ modelRoot: resolve("static/models") + "/", device: "cpu" });
const all: { cat: string; text: string }[] = [];
for (const q of data.slice(100, 106)) {
  await store.wipeAll();
  const v = new Vault();
  await v.setup("audit passphrase!", 1000);
  v.embedder = embed;
  for (const s of q.haystack_sessions) for (const t of s) if (t.role === "user") await v.ingestMessage(t.content, { site: "audit", kind: "user_message" });
  for (const m of v.list()) all.push({ cat: m.category, text: m.text });
}
const counts: Record<string, number> = {};
for (const m of all) counts[m.cat] = (counts[m.cat] ?? 0) + 1;
console.log("memories", all.length, JSON.stringify(counts));
let seed = 3;
const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const sample = [...all].sort(() => rnd() - 0.5).slice(0, 60);
sample.forEach((m, i) => console.log(`${i + 1}\t${m.cat}\t${m.text.slice(0, 160)}`));
