// Store screenshots (1280x800) of the real built extension with a small DEMO library.
// The demo conversations are illustrative UI content, not user data or results.
import { chromium } from "playwright-core";
import { strToU8, zipSync } from "fflate";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const EXE = process.env.CHROMIUM ?? join(process.env.HOME, "Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing");
const ext = resolve("dist");
const tmp = mkdtempSync(join(tmpdir(), "shots-"));
const day = (d) => `2026-${d}T15:00:00Z`;
const demo = [
  ["claude", "Sourdough starter troubleshooting", "10-02", [["human", "My sourdough starter smells like nail polish remover. Is it dead?"], ["assistant", "Not dead! An acetone smell means it's hungry. Feed it twice a day at a 1:1:1 ratio for a few days and the smell will fade."]]],
  ["claude", "Cover letter: data analyst role", "09-18", [["human", "Draft a cover letter for a data analyst role at a logistics company."], ["assistant", "Dear Hiring Manager, I'm excited to apply for the Data Analyst position..."]]],
  ["claude", "Kyoto 4-day itinerary", "08-30", [["human", "Plan 4 days in Kyoto in April, I love temples and food markets."], ["assistant", "Day 1: Fushimi Inari at sunrise, then Nishiki Market for lunch..."]]],
];
const gpt = [
  ["Lease and rent increase", "10-11", "Can my landlord raise the rent in the middle of a fixed-term lease in Colorado?", "Generally no. During a fixed-term lease the rent is locked unless the lease itself allows increases. Check for an escalation clause."],
  ["SQL: monthly churn query", "10-07", "Write a SQL query for monthly customer churn from a subscriptions table.", "Here's a query using a CTE that counts customers active at the start of each month and those who cancelled..."],
  ["Kitchen remodel budget", "09-25", "Help me budget a kitchen remodel with quartz countertops.", "Quartz countertops typically cost 50 to 100 dollars per square foot installed. A mid-range remodel..."],
].map(([title, d, u, a], i) => ({ id: `demo-${i}`, conversation_id: `demo-${i}`, title, create_time: Date.parse(day(d)) / 1000, update_time: Date.parse(day(d)) / 1000 + 600, current_node: "a",
  mapping: { r: { parent: null, message: null }, u: { parent: "r", message: { author: { role: "user" }, content: { content_type: "text", parts: [u] } } }, a: { parent: "u", message: { author: { role: "assistant" }, content: { content_type: "text", parts: [a] } } } } }));
const claude = demo.map(([, name, d, msgs], i) => ({ uuid: `demo-c-${i}`, name, created_at: day(d), updated_at: day(d), chat_messages: msgs.map(([sender, text]) => ({ sender, text })) }));
writeFileSync(join(tmp, "chatgpt.zip"), zipSync({ "conversations.json": strToU8(JSON.stringify(gpt)) }));
writeFileSync(join(tmp, "claude.zip"), zipSync({ "conversations.json": strToU8(JSON.stringify(claude)) }));

const ctx = await chromium.launchPersistentContext(join(tmp, "p"), { executablePath: EXE, headless: true, viewport: { width: 1280, height: 800 },
  args: [`--disable-extensions-except=${ext}`, `--load-extension=${ext}`, "--headless=new"] });
let [sw] = ctx.serviceWorkers();
sw ??= await ctx.waitForEvent("serviceworker");
const id = new URL(sw.url()).host;
let app;
for (let i = 0; !app && i < 40; i++) { await new Promise((r) => setTimeout(r, 250)); app = ctx.pages().find((p) => p.url().includes("app.html")); }
await app.setViewportSize({ width: 1280, height: 800 });
await app.waitForSelector("text=Every AI chat you've had");
await app.screenshot({ path: "store/screenshots/1-welcome.png" });
await app.click("text=Create my private library");
await app.waitForSelector("text=You're set up");
for (let i = 0; i < 80; i++) { const s = await app.evaluate(() => chrome.runtime.sendMessage({ type: "state" })); if (s.state.model !== "loading") break; await app.waitForTimeout(500); }
await app.goto(`chrome-extension://${id}/app.html#import`);
await app.screenshot({ path: "store/screenshots/4-import.png" });
await app.setInputFiles('input[type="file"]', [join(tmp, "chatgpt.zip"), join(tmp, "claude.zip")]);
await app.waitForSelector("text=/Done:/", { timeout: 60000 });
await app.goto(`chrome-extension://${id}/app.html#`);
await app.fill("#q", "is my bread culture ruined");
await app.waitForSelector(".result");
await app.waitForTimeout(400);
await app.screenshot({ path: "store/screenshots/2-search.png" });
await app.click(".result >> nth=0");
await app.waitForSelector(".msg");
await app.screenshot({ path: "store/screenshots/3-continue.png" });
await ctx.close();
console.log("screenshots written to store/screenshots/");
