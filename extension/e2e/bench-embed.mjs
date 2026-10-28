// In-browser indexing throughput: import N real LongMemEval sessions, time until meaning indexing is done.
// Compares the extension as built (dist/) with and without cross-origin isolation (multi-threaded WASM).
import { chromium } from "playwright-core";
import { strToU8, zipSync } from "fflate";
import { cpSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";

const EXE = join(process.env.HOME, "Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing");
const N = Number(process.argv[2] ?? 150);
const lme = JSON.parse(readFileSync(join(homedir(), ".cache/aegis-bench/longmemeval_s_cleaned.json"), "utf8"));
const seen = new Set();
const convs = [];
for (const q of lme) for (const [i, sid] of q.haystack_session_ids.entries()) {
  if (seen.has(sid) || convs.length >= N) continue;
  seen.add(sid);
  convs.push({ uuid: `bench-${convs.length}`, name: "", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    chat_messages: q.haystack_sessions[i].map((t) => ({ sender: t.role === "user" ? "human" : "assistant", text: t.content })) });
}
const tmp = mkdtempSync(join(tmpdir(), "bench-"));
writeFileSync(join(tmp, "claude.zip"), zipSync({ "conversations.json": strToU8(JSON.stringify(convs)) }));

async function run(label, coi) {
  const dir = join(tmp, label);
  cpSync(resolve("dist"), dir, { recursive: true });
  const m = JSON.parse(readFileSync(join(dir, "manifest.json"), "utf8"));
  if (coi) { m.cross_origin_embedder_policy = { value: "require-corp" }; m.cross_origin_opener_policy = { value: "same-origin" }; }
  else { delete m.cross_origin_embedder_policy; delete m.cross_origin_opener_policy; }
  writeFileSync(join(dir, "manifest.json"), JSON.stringify(m));
  const ctx = await chromium.launchPersistentContext(join(tmp, `p-${label}`), { executablePath: EXE, headless: true, args: [`--disable-extensions-except=${dir}`, `--load-extension=${dir}`, "--headless=new"] });
  try {
    let [sw] = ctx.serviceWorkers(); sw ??= await ctx.waitForEvent("serviceworker");
    const id = new URL(sw.url()).host;
    const app = await ctx.newPage();
    await app.goto(`chrome-extension://${id}/app.html#welcome`);
    await app.click("text=Create my private library");
    await app.waitForSelector("text=You're set up");
    const st = () => app.evaluate(() => chrome.runtime.sendMessage({ type: "state" }));
    for (let i = 0; i < 120 && (await st()).state.model === "loading"; i++) await app.waitForTimeout(250);
    await app.goto(`chrome-extension://${id}/app.html#import`);
    const t0 = Date.now();
    await app.setInputFiles('input[type="file"]', join(tmp, "claude.zip"));
    await app.waitForSelector("text=/Done:/", { timeout: 600000 });
    const saved = Date.now() - t0;
    let s;
    while ((s = await st()).state.indexing > 0) await app.waitForTimeout(500);
    const total = Date.now() - t0;
    const chunks = s.state.stats.chunks;
    console.log(`${label.padEnd(10)} ${N} conversations, ${chunks} chunks: saved+keyword-searchable in ${(saved / 1000).toFixed(1)} s; meaning index done in ${(total / 1000).toFixed(1)} s (${(chunks / (total / 1000)).toFixed(0)} chunks/s)`);
  } finally {
    await ctx.close();
  }
}
await run("1-thread", false);
await run("threaded", true);
