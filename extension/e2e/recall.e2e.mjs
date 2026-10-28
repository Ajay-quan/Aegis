// End-to-end: real Chromium + built extension. Stand-in pages for chatgpt.com / claude.ai.
import { chromium } from "playwright-core";
import { strToU8, zipSync } from "fflate";
import { mkdtempSync, writeFileSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import assert from "node:assert/strict";

const EXE = process.env.CHROMIUM ?? join(process.env.HOME, "Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing");
const ext = resolve("dist");
const tmp = mkdtempSync(join(tmpdir(), "recall-e2e-"));
const step = (s) => console.log(`  ✓ ${s}`);

// --- export fixtures in the real formats
const gpt = [{
  id: "11111111-aaaa", conversation_id: "11111111-aaaa", title: "Lease and rent", create_time: 1767225600, update_time: 1767229200, current_node: "a1",
  mapping: {
    r: { id: "r", parent: null, children: ["u1"], message: null },
    u1: { id: "u1", parent: "r", children: ["a1"], message: { author: { role: "user" }, create_time: 1767225600, content: { content_type: "text", parts: ["Can my landlord raise the rent in the middle of a fixed-term lease in Colorado?"] } } },
    a1: { id: "a1", parent: "u1", children: [], message: { author: { role: "assistant" }, recipient: "all", create_time: 1767225660, content: { content_type: "text", parts: ["Generally no. During a fixed-term lease the rent is locked unless the lease itself allows increases."] } } },
  },
}];
const topics = ["Explain recursion", "Best pizza dough hydration", "How do tides work", "Write a haiku about rain", "Python list comprehension", "History of the printing press", "Tips for a job interview", "How to repot a monstera"];
const filler = Array.from({ length: 40 }, (_, i) => ({
  uuid: `c0ffee00-${String(i).padStart(4, "0")}`, name: `Topic ${i}`, created_at: "2026-02-01T10:00:00Z", updated_at: "2026-02-01T10:05:00Z",
  chat_messages: [{ sender: "human", text: `${topics[i % 8]} (${i})` }, { sender: "assistant", text: "Here is a detailed answer about that topic with several useful points." }],
}));
const claude = [{
  uuid: "c1aude00-0001", name: "Sourdough troubleshooting", created_at: "2026-03-01T09:00:00Z", updated_at: "2026-03-01T09:30:00Z",
  chat_messages: [{ sender: "human", text: "My sourdough starter smells like nail polish remover, is it dead?" }, { sender: "assistant", content: [{ type: "text", text: "Not dead: an acetone smell means it's hungry. Feed it more often." }] }],
}, ...filler];
writeFileSync(join(tmp, "chatgpt-export.zip"), zipSync({ "conversations.json": strToU8(JSON.stringify(gpt)), "chat.html": strToU8("<html></html>") }));
writeFileSync(join(tmp, "claude-export.zip"), zipSync({ "conversations.json": strToU8(JSON.stringify(claude)), "users.json": strToU8("[]") }));

const ctx = await chromium.launchPersistentContext(join(tmp, "profile"), {
  executablePath: EXE, headless: true, acceptDownloads: true,
  args: [`--disable-extensions-except=${ext}`, `--load-extension=${ext}`, "--headless=new"],
});
const errors = [];
const watch = (p, name) => {
  p.on("pageerror", (e) => errors.push(`${name}: ${e.message}`));
  p.on("console", (m) => m.type() === "error" && errors.push(`${name} console: ${m.text()}`));
};
try {
  let [sw] = ctx.serviceWorkers();
  sw ??= await ctx.waitForEvent("serviceworker");
  const id = new URL(sw.url()).host;
  step("extension loaded");

  await ctx.route("https://chatgpt.com/**", (r) => r.fulfill({ contentType: "text/html", body: `<!doctype html><title>Kitchen remodel budget - ChatGPT</title><body><div id="thread"></div><div id="prompt-textarea" contenteditable="true"></div></body>` }));
  await ctx.route("https://claude.ai/**", (r) => r.fulfill({ contentType: "text/html", body: `<!doctype html><title>Claude</title><body><div class="ProseMirror" contenteditable="true"></div></body>` }));

  // Welcome tab opens on install
  let app = ctx.pages().find((p) => p.url().includes("app.html"));
  for (let i = 0; !app && i < 20; i++) {
    await new Promise((r) => setTimeout(r, 250));
    app = ctx.pages().find((p) => p.url().includes("app.html"));
  }
  assert.ok(app, "welcome tab should open on install");
  watch(app, "app");
  await app.waitForSelector("text=Every AI chat you've had");
  step("welcome page opened on install");
  await app.click("text=Create my private library");
  await app.waitForSelector("text=You're set up");
  step("library created (device-encrypted, no passphrase)");

  const st = () => app.evaluate(() => chrome.runtime.sendMessage({ type: "state" }));
  for (let i = 0; i < 80 && (await st()).state.model === "loading"; i++) await app.waitForTimeout(500);
  assert.equal((await st()).state.model, "ready", JSON.stringify((await st()).state));
  step("on-device search model ready");

  // Import
  await app.goto(`chrome-extension://${id}/app.html#import`);
  await app.setInputFiles('input[type="file"]', [join(tmp, "chatgpt-export.zip"), join(tmp, "claude-export.zip")]);
  await app.waitForSelector("text=/Done: 42 new/", { timeout: 120000 });
  step("imported ChatGPT + Claude export zips (42 conversations)");

  // Keyword search
  await app.goto(`chrome-extension://${id}/app.html#`);
  await app.fill("#q", "landlord rent lease");
  await app.waitForSelector(".result h3:has-text('Lease and rent')");
  assert.equal(await app.locator(".result h3").first().textContent(), "Lease and rent");
  assert.ok((await app.locator(".result mark").count()) > 0, "highlights");
  step("keyword search ranks the right chat first, with highlights");

  // Meaning search: few shared words with the chat
  await app.fill("#q", "is my bread culture ruined? weird chemical odor");
  await app.waitForFunction(() => document.querySelector(".result h3")?.textContent === "Sourdough troubleshooting", null, { timeout: 10000 });
  step("meaning search ranks 'starter smells like nail polish' first for a paraphrase");

  // Filters
  await app.fill("#q", "rent");
  await app.waitForSelector(".result h3:has-text('Lease and rent')");
  await app.click("button.chip:has-text('Claude')");
  await app.waitForFunction(() => ![...document.querySelectorAll(".result h3")].some((e) => e.textContent === "Lease and rent"));
  await app.click("button.chip:has-text('Claude')");
  step("platform filter works");

  // Viewer + continue in Claude
  await app.fill("#q", "landlord");
  await app.click(".result:has-text('Lease and rent')");
  await app.waitForSelector("h1:has-text('Lease and rent')");
  assert.ok(await app.locator(".msg.focus").count(), "viewer focuses the matching message");
  const pageP = ctx.waitForEvent("page");
  await app.click(".row:has-text('Continue this chat in') button.chip:has-text('Claude')");
  const target = await pageP;
  // Extension-opened tabs aren't intercepted by Playwright on their first load (they hit the real
  // claude.ai, which shows an error page). Like a user passing a login wall, navigate the same tab.
  await target.waitForLoadState();
  await target.goto("https://claude.ai/new");
  await target.waitForFunction(() => document.querySelector(".ProseMirror")?.innerText.includes("Generally no."), null, { timeout: 10000 });
  assert.match(await target.locator(".ProseMirror").innerText(), /continuing a conversation I had with ChatGPT/);
  step("viewer opens at the match; 'Continue in Claude' pre-fills Claude's editor (not sent)");
  await target.reload();
  await target.waitForTimeout(1500);
  assert.equal((await target.locator(".ProseMirror").innerText()).trim(), "", "handoff is delivered once");
  step("handoff is one-time (a reload gets nothing)");
  await target.close();

  // Live capture on chatgpt.com, waiting for streaming to finish
  const site = await ctx.newPage();
  await site.goto("https://chatgpt.com/c/22222222-bbbb");
  await site.evaluate(() => {
    const add = (role, t) => { const d = document.createElement("div"); d.dataset.messageAuthorRole = role; d.innerText = t; document.getElementById("thread").append(d); };
    add("user", "Help me budget a kitchen remodel with quartz countertops");
    const stop = document.createElement("button"); stop.dataset.testid = "stop-button"; document.body.append(stop);
    add("assistant", "Quartz countertops typically cost");
  });
  await site.waitForTimeout(3500);
  let found = await app.evaluate(() => chrome.runtime.sendMessage({ type: "get", id: "chatgpt:22222222-bbbb" }));
  assert.equal(found.conversation, undefined, "must not save while the reply is streaming");
  await site.evaluate(() => {
    document.querySelector('[data-testid="stop-button"]').remove();
    document.querySelector('[data-message-author-role="assistant"]').innerText = "Quartz countertops typically cost 50 to 100 dollars per square foot installed.";
  });
  for (let i = 0; i < 20 && !found.conversation; i++) {
    await site.waitForTimeout(500);
    found = await app.evaluate(() => chrome.runtime.sendMessage({ type: "get", id: "chatgpt:22222222-bbbb" }));
  }
  assert.equal(found.conversation?.messages.length, 2);
  assert.match(found.conversation.messages[1].text, /50 to 100 dollars/);
  assert.equal(found.conversation.title, "Kitchen remodel budget");
  step("live capture saves both sides only after the reply finishes streaming");

  // Popup quick search
  const popup = await ctx.newPage();
  watch(popup, "popup");
  await popup.goto(`chrome-extension://${id}/popup.html`);
  await popup.fill("#q", "quartz countertops");
  await popup.waitForSelector(".result h3:has-text('Kitchen remodel budget')");
  step("popup quick search finds the live-captured chat");
  await popup.close();

  // At-rest encryption
  const raw = await app.evaluate(() => new Promise((res) => {
    const r = indexedDB.open("aegismem-recall");
    r.onsuccess = () => { const g = r.result.transaction("convs").objectStore("convs").getAll(); g.onsuccess = () => res(JSON.stringify(g.result)); };
  }));
  assert.doesNotMatch(raw, /landlord|sourdough|quartz/i);
  step("IndexedDB holds only ciphertext");

  // Backup -> delete all -> restore
  await app.goto(`chrome-extension://${id}/app.html#settings`);
  await app.fill('input[placeholder^="Backup password"]', "backup password 123");
  const dl = app.waitForEvent("download");
  await app.click("text=Download encrypted backup");
  const backupPath = join(tmp, "backup.json");
  await (await dl).saveAs(backupPath);
  assert.doesNotMatch(readFileSync(backupPath, "utf8"), /landlord/);
  app.once("dialog", (d) => d.accept());
  await app.click("text=Delete all conversations");
  for (let i = 0; i < 20 && (await st()).state.stats.conversations !== 0; i++) await app.waitForTimeout(250);
  assert.equal((await st()).state.stats.conversations, 0);
  await app.goto(`chrome-extension://${id}/app.html#settings`);
  await app.fill('input[placeholder^="Backup password"]', "backup password 123");
  await app.setInputFiles('input[type="file"][accept=".json"]', backupPath);
  await app.waitForSelector("text=/Restored 43 conversations/", { timeout: 120000 });
  step("encrypted backup → delete all → restore (43 conversations)");

  // Passphrase mode: add, lock, unlock
  await app.goto(`chrome-extension://${id}/app.html#settings`);
  await app.fill('input[placeholder="New passphrase (10+ characters)"]', "correct horse battery");
  await app.click("text=Add a passphrase");
  await app.waitForSelector(".key");
  await app.click("text=I saved it");
  await app.evaluate(() => chrome.runtime.sendMessage({ type: "lock" }));
  await app.goto(`chrome-extension://${id}/app.html#`);
  await app.waitForSelector("text=Unlock AegisMem");
  await app.fill('input[placeholder="Passphrase"]', "wrong passphrase!");
  await app.click("button:has-text('Unlock')");
  await app.waitForSelector("text=Wrong passphrase");
  await app.fill('input[placeholder="Passphrase"]', "correct horse battery");
  await app.click("button:has-text('Unlock')");
  await app.waitForSelector("text=/conversations ·/");
  await app.fill("#q", "sourdough");
  await app.waitForSelector(".result h3:has-text('Sourdough troubleshooting')");
  step("passphrase added → lock → wrong passphrase rejected → unlock → search works");

  // Extension pages cannot reach the network
  const net = await app.evaluate(async () => { try { await fetch("https://example.com"); return "allowed"; } catch { return "blocked"; } });
  assert.equal(net, "blocked");
  step("extension pages cannot reach the network (CSP connect-src 'self')");

  const real = errors.filter((e) => !/example\.com|Content Security Policy/.test(e));
  assert.deepEqual(real, [], `page errors:\n${real.join("\n")}`);
  step("no page errors");
  console.log("E2E PASSED");
} finally {
  await ctx.close();
}
