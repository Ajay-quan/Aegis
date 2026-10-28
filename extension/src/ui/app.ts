import { strToU8, zipSync } from "fflate";
import { decryptBackup, encryptBackup, type BackupFile } from "../core/backup";
import { buildAsk, buildContinuation, toMarkdown } from "../core/handoff";
import type { Result } from "../core/library";
import { PLATFORMS, type Conversation, type Platform } from "../core/types";
import { ADAPTERS } from "../content/adapters";
import { detectAndParse, type InputFile } from "../importers/detect";
import { send, type LibState, type Settings } from "../protocol";
import { download, h, highlighted, when } from "./dom";

const ALL: Platform[] = ["chatgpt", "claude", "gemini", "perplexity"];
const main = document.querySelector("main")!;
const q = document.getElementById("q") as HTMLInputElement;
const status = document.getElementById("status")!;

let state: LibState | null = null;
const filters: { platforms: Set<Platform>; days: number; role: "" | "user" | "assistant" } = { platforms: new Set(), days: 0, role: "" };
let lastResults: Result[] = [];

async function call<T extends keyof import("../protocol").Response>(req: Parameters<typeof send>[0]) {
  const r = await send(req);
  if (!r.ok) throw new Error(r.error);
  return r;
}

function platformBadge(p: Platform, extra?: string): HTMLElement {
  return h("span", { class: "badge" }, h("span", { class: `dot ${p}` }), PLATFORMS[p].label, extra ? ` · ${extra}` : "");
}

async function refreshState(): Promise<LibState> {
  state = (await call({ type: "state" })).state!;
  status.replaceChildren(
    !state.exists ? h("span", { class: "pill warn" }, "Not set up")
    : !state.unlocked ? h("span", { class: "pill warn" }, "Locked")
    : state.model === "ready" && state.indexing ? h("span", { class: "pill warn", title: "Keyword search works now; meaning search is being added on-device" }, `Indexing… ${Math.round((100 * ((state.stats?.conversations ?? 0) - state.indexing)) / Math.max(1, state.stats?.conversations ?? 1))}%`)
    : state.model === "ready" ? h("span", { class: "pill", title: "On-device meaning + keyword search" }, "Smart search")
    : state.model === "loading" ? h("span", { class: "pill warn" }, "Loading search model…")
    : h("span", { class: "pill warn", title: state.modelError ?? "" }, "Keyword search only"),
  );
  if (state.model === "loading" || state.indexing) setTimeout(() => void refreshState(), 1500);
  return state;
}

function setNav(route: string): void {
  for (const a of document.querySelectorAll<HTMLAnchorElement>("nav a")) a.toggleAttribute("aria-current", a.getAttribute("href") === `#${route}`);
  for (const a of document.querySelectorAll<HTMLAnchorElement>("nav a[aria-current]")) a.setAttribute("aria-current", "page");
}

// ---------------------------------------------------------------- routing
async function route(): Promise<void> {
  const hash = location.hash.slice(1);
  const [name, ...rest] = hash.split("/");
  const s = await refreshState();
  if (!s.exists || name === "welcome") return welcome();
  if (!s.unlocked) return lockScreen();
  setNav(name || "search");
  if (name === "c") return viewer(decodeURIComponent(rest[0] ?? ""), Number(rest[1] ?? -1));
  if (name === "import") return importView();
  if (name === "settings") return settingsView();
  return searchView();
}

// ---------------------------------------------------------------- welcome / setup
async function welcome(): Promise<void> {
  setNav("");
  if (state?.exists) {
    main.replaceChildren(h("div", { class: "card stack" }, h("h1", {}, "You're set up"),
      h("p", {}, "Next: bring in your history so search is useful from day one."),
      h("div", { class: "row" }, h("a", { href: "#import" }, h("button", { class: "primary" }, "Import my AI history")), h("a", { href: "#" }, h("button", {}, "Go to search")))));
    return;
  }
  let mode: "device" | "passphrase" = "device";
  const p1 = h("input", { type: "password", placeholder: "Passphrase (10+ characters)" }) as HTMLInputElement;
  const p2 = h("input", { type: "password", placeholder: "Repeat passphrase" }) as HTMLInputElement;
  const passBox = h("div", { class: "stack", hidden: true }, p1, p2, h("p", { class: "small muted" }, "You'll get a recovery key. If you lose both, nobody (including us) can recover your history."));
  const err = h("p", { class: "err" });
  const opt = (m: typeof mode, title: string, desc: string) => {
    const r = h("input", { type: "radio", name: "mode", checked: m === mode, onchange: () => { mode = m; passBox.hidden = m !== "passphrase"; } });
    return h("label", { class: "card row", style: "align-items:flex-start;cursor:pointer" }, r, h("div", {}, h("strong", {}, title), h("div", { class: "small muted" }, desc)));
  };
  const caps = ADAPTERS.map((a) => h("label", { class: "row" }, h("input", { type: "checkbox", checked: true, "data-p": a.platform }), `${PLATFORMS[a.platform].label}${a.verified ? "" : " (beta)"}`));
  const go = h("button", { class: "primary", onclick: async () => {
    err.textContent = "";
    if (mode === "passphrase" && p1.value !== p2.value) return void (err.textContent = "Passphrases don't match.");
    go.disabled = true;
    go.textContent = "Setting up…";
    try {
      const capture = Object.fromEntries(caps.map((l) => { const i = l.querySelector("input")!; return [i.dataset.p, i.checked]; })) as Settings["capture"];
      await call({ type: "settings", set: { capture, onboarded: true } });
      if (mode === "device") {
        await call({ type: "setupDevice" });
        location.hash = "#welcome";
        await route();
      } else {
        const r = await call({ type: "setupPassphrase", passphrase: p1.value });
        showRecovery(r.recoveryKey!, () => { location.hash = "#welcome"; void route(); });
      }
    } catch (e) {
      err.textContent = (e as Error).message;
      go.disabled = false;
      go.textContent = "Create my private library";
    }
  } }, "Create my private library");
  main.replaceChildren(h("div", { class: "stack" },
    h("h1", {}, "Every AI chat you've had, searchable in one place"),
    h("p", { class: "muted" }, "AegisMem keeps a private, encrypted copy of your ChatGPT, Claude, Gemini and Perplexity conversations on this device, so you can find any answer and carry any chat to another AI. No account, no servers: nothing ever leaves your computer unless you choose to send it to an AI."),
    h("h2", {}, "1. How should your library be protected?"),
    opt("device", "Encrypted on this device (recommended)", "No password to remember. Your history is encrypted at rest and opens automatically in this browser profile."),
    opt("passphrase", "Encrypted + passphrase", "Also locks after inactivity. Anyone using this browser needs your passphrase to read your history."),
    passBox,
    h("h2", {}, "2. Save new chats automatically on"),
    h("div", { class: "grid3" }, ...caps),
    h("p", { class: "small muted" }, "Saved after each reply, on this device only. You can change this any time in Settings."),
    h("div", { class: "row" }, go), err));
}

function showRecovery(key: string, done: () => void): void {
  main.replaceChildren(h("div", { class: "card stack" }, h("h1", {}, "Save your recovery key"),
    h("p", {}, "It's shown only once. Keep it in a password manager. It's the only way back in if you forget your passphrase."),
    h("div", { class: "key" }, key),
    h("div", { class: "row" }, h("button", { onclick: () => navigator.clipboard.writeText(key) }, "Copy"), h("button", { class: "primary", onclick: done }, "I saved it"))));
}

function lockScreen(): void {
  setNav("");
  const p = h("input", { type: "password", placeholder: "Passphrase", autofocus: true }) as HTMLInputElement;
  const err = h("p", { class: "err" });
  const unlock = async () => {
    try {
      await call({ type: "unlock", passphrase: p.value });
      await route();
    } catch (e) {
      err.textContent = (e as Error).message;
    }
  };
  p.addEventListener("keydown", (e) => e.key === "Enter" && void unlock());
  const recover = () => {
    const k = h("input", { type: "text", placeholder: "Recovery key" }) as HTMLInputElement;
    const n = h("input", { type: "password", placeholder: "New passphrase (10+ characters)" }) as HTMLInputElement;
    const e2 = h("p", { class: "err" });
    main.replaceChildren(h("div", { class: "card stack", style: "max-width:460px;margin:40px auto" }, h("h1", {}, "Recover your library"), k, n,
      h("div", { class: "row" }, h("button", { class: "primary", onclick: async () => {
        try { await call({ type: "recover", recoveryKey: k.value, newPassphrase: n.value }); await route(); } catch (x) { e2.textContent = (x as Error).message; }
      } }, "Recover"), h("button", { onclick: lockScreen }, "Back")), e2));
  };
  main.replaceChildren(h("div", { class: "card stack", style: "max-width:460px;margin:40px auto" }, h("h1", {}, "Unlock AegisMem"), p,
    h("div", { class: "row" }, h("button", { class: "primary", onclick: unlock }, "Unlock"), h("button", { class: "ghost", onclick: recover }, "Forgot passphrase?")), err));
  p.focus();
}

// ---------------------------------------------------------------- search
function filterBar(): HTMLElement {
  const chips = ALL.map((p) => h("button", { class: "chip", "aria-pressed": String(filters.platforms.has(p)), onclick: () => {
    if (filters.platforms.has(p)) filters.platforms.delete(p);
    else filters.platforms.add(p);
    void searchView();
  } }, h("span", { class: `dot ${p}` }), " ", PLATFORMS[p].label));
  const days = h("select", { onchange: (e: Event) => { filters.days = Number((e.target as HTMLSelectElement).value); void searchView(); } },
    ...[[0, "Any time"], [7, "Past week"], [30, "Past month"], [365, "Past year"]].map(([v, l]) => h("option", { value: String(v), selected: filters.days === v }, String(l))));
  const role = h("select", { onchange: (e: Event) => { filters.role = (e.target as HTMLSelectElement).value as typeof filters.role; void searchView(); } },
    h("option", { value: "", selected: filters.role === "" }, "Anywhere"), h("option", { value: "user", selected: filters.role === "user" }, "In my messages"), h("option", { value: "assistant", selected: filters.role === "assistant" }, "In AI replies"));
  (days as HTMLSelectElement).style.width = (role as HTMLSelectElement).style.width = "auto";
  return h("div", { class: "row filters" }, ...chips, days, role);
}

function resultCard(r: Result, query: string): HTMLElement {
  return h("a", { class: "card result", href: `#c/${encodeURIComponent(r.convId)}/${r.best.msgIndex}` },
    h("div", { class: "row" }, platformBadge(r.platform, when(r.updatedAt)), r.matches > 1 ? h("span", { class: "faint small" }, `${r.matches} matching passages`) : null),
    h("h3", {}, r.title || "Untitled"),
    h("div", { class: "snip" }, r.best.role === "title" ? h("span", { class: "faint" }, "Matched the title") : h("span", {}, h("span", { class: "faint" }, r.best.role === "user" ? "You: " : "AI: "), highlighted(r.best.snippet))),
    query ? null : null);
}

async function searchView(): Promise<void> {
  setNav("search");
  const query = q.value.trim();
  const stats = state?.stats;
  if (!stats?.conversations) {
    main.replaceChildren(h("div", { class: "card stack" }, h("h1", {}, "Your library is empty"),
      h("p", {}, "Import your existing history from ChatGPT, Claude or Gemini (takes a few minutes), or just keep chatting: new conversations are saved automatically."),
      h("a", { href: "#import" }, h("button", { class: "primary" }, "Import my AI history"))));
    return;
  }
  const bar = filterBar();
  if (!query) {
    const recent = (await call({ type: "recent", limit: 30 })).conversations!.filter((c) => !filters.platforms.size || filters.platforms.has(c.platform));
    main.replaceChildren(bar, h("p", { class: "muted small" }, `${stats.conversations.toLocaleString()} conversations · ${stats.messages.toLocaleString()} messages. Type to search by words or meaning.`),
      h("div", { class: "results" }, ...recent.map((c) => h("a", { class: "card result", href: `#c/${encodeURIComponent(c.id)}` },
        platformBadge(c.platform, when(c.updatedAt)), h("h3", {}, c.title || "Untitled"),
        h("div", { class: "snip" }, (c.messages[0]?.text ?? "").slice(0, 160))))));
    return;
  }
  const t0 = performance.now();
  const opts = {
    platforms: filters.platforms.size ? [...filters.platforms] : undefined,
    role: filters.role || undefined,
    from: filters.days ? Date.now() - filters.days * 86_400_000 : undefined,
    limit: 30,
  };
  lastResults = (await call({ type: "search", query, opts })).results!;
  if (q.value.trim() !== query) return; // a newer query is in flight
  const ms = Math.round(performance.now() - t0);
  const ask = h("div", { class: "row" }, h("span", { class: "muted small" }, "Ask an AI using these results:"),
    ...(["chatgpt", "claude", "gemini"] as Platform[]).map((p) => h("button", { class: "chip", onclick: () => askWith(p, query) }, PLATFORMS[p].label)));
  main.replaceChildren(bar,
    h("p", { class: "muted small" }, `${lastResults.length} conversation${lastResults.length === 1 ? "" : "s"} · ${ms} ms`),
    lastResults.length ? ask : h("p", {}, "No matches. Try other words, or remove filters."),
    h("div", { class: "results" }, ...lastResults.map((r) => resultCard(r, query))));
}

async function askWith(p: Platform, question: string): Promise<void> {
  const top = lastResults.slice(0, 8);
  const text = buildAsk(question, top.map((r) => ({ platform: r.platform, title: r.title, date: r.updatedAt.slice(0, 10), text: r.best.text })));
  await call({ type: "handoff", platform: p, text });
}

// ---------------------------------------------------------------- viewer
async function viewer(id: string, focus: number): Promise<void> {
  setNav("");
  const c = (await call({ type: "get", id })).conversation;
  if (!c) {
    main.replaceChildren(h("p", {}, "This conversation isn't in your library (it may have been deleted)."));
    return;
  }
  const label = PLATFORMS[c.platform].label;
  const cont = (["chatgpt", "claude", "gemini", "perplexity"] as Platform[]).map((p) =>
    h("button", { class: "chip", onclick: () => call({ type: "handoff", platform: p, text: buildContinuation(c) }) }, PLATFORMS[p].label));
  const msgs = c.messages.map((m, i) => h("div", { class: `msg ${m.role}${i === focus ? " focus" : ""}`, id: `m${i}` },
    h("div", { class: "who" }, m.role === "user" ? "You" : label, m.at ? h("span", { class: "faint" }, ` · ${when(m.at)}`) : null), m.text));
  main.replaceChildren(h("div", { class: "stack" },
    h("a", { href: "#", class: "small", onclick: (e: Event) => { e.preventDefault(); history.back(); } }, "← Back"),
    h("h1", {}, c.title || "Untitled"),
    h("div", { class: "row" }, platformBadge(c.platform, `${when(c.createdAt)} → ${when(c.updatedAt)} · ${c.messages.length} messages · ${c.source === "import" ? "imported" : "saved live"}`)),
    h("div", { class: "row" },
      h("a", { href: PLATFORMS[c.platform].url(c.nativeId), target: "_blank", rel: "noopener" }, h("button", {}, `Open in ${label} ↗`)),
      h("button", { onclick: () => navigator.clipboard.writeText(toMarkdown(c)) }, "Copy as Markdown"),
      h("button", { onclick: () => download(`${c.title.replace(/[^\w -]+/g, "").slice(0, 60) || "conversation"}.md`, toMarkdown(c), "text/markdown") }, "Download .md"),
      h("button", { class: "danger", onclick: async () => {
        if (!confirm("Delete this conversation from AegisMem? (It stays on the AI site.)")) return;
        await call({ type: "delete", id: c.id });
        location.hash = "#";
      } }, "Delete")),
    h("div", { class: "row" }, h("span", { class: "muted small" }, "Continue this chat in:"), ...cont),
    ...msgs));
  if (focus >= 0) document.getElementById(`m${focus}`)?.scrollIntoView({ block: "center" });
}

// ---------------------------------------------------------------- import
function importView(): void {
  setNav("import");
  const log = h("div", { class: "stack" });
  const input = h("input", { type: "file", multiple: true, accept: ".zip,.json", hidden: true, onchange: () => void ingest([...(input as HTMLInputElement).files!]) }) as HTMLInputElement;
  const drop = h("div", { class: "drop" }, h("p", {}, h("strong", {}, "Drop your export files here")), h("p", { class: "muted small" }, ".zip or .json from ChatGPT, Claude or Google Takeout (Gemini). Files are read on this device and never uploaded."),
    h("button", { class: "primary", onclick: () => input.click() }, "Choose files"), input);
  drop.addEventListener("dragover", (e) => { e.preventDefault(); drop.classList.add("over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("over"));
  drop.addEventListener("drop", (e) => { e.preventDefault(); drop.classList.remove("over"); void ingest([...(e.dataTransfer?.files ?? [])]); });
  const how = (p: Platform, steps: (string | HTMLElement)[]) => h("div", { class: "card" }, platformBadge(p), h("ol", { class: "steps small" }, ...steps.map((s) => h("li", {}, s))));
  main.replaceChildren(h("div", { class: "stack" }, h("h1", {}, "Import your AI history"),
    h("p", { class: "muted" }, "Each service can email you a copy of all your chats. Request them, then drop the files here. New chats are also saved automatically as you use each site."),
    h("div", { class: "grid3" },
      how("chatgpt", ["Open ChatGPT → Settings → Data controls", "Click “Export data” → Confirm", "Download the .zip from the email (link expires in 24h)"]),
      how("claude", ["Open Claude → Settings → Privacy", "Click “Export data”", "Download the .zip from the email"]),
      how("gemini", [h("span", {}, "Open ", h("a", { href: "https://takeout.google.com", target: "_blank", rel: "noopener" }, "takeout.google.com")), "Deselect all → select “My Activity” → filter to “Gemini Apps”, format JSON", "Download the .zip when ready"])),
    drop, log));

  async function ingest(files: File[]): Promise<void> {
    if (!files.length) return;
    const line = (t: string | Node, cls = "") => log.append(h("div", { class: cls }, t));
    log.replaceChildren();
    line(`Reading ${files.length} file${files.length > 1 ? "s" : ""}…`, "muted");
    const inputs: InputFile[] = [];
    for (const f of files) inputs.push({ name: f.name, bytes: new Uint8Array(await f.arrayBuffer()) });
    const parsed = detectAndParse(inputs);
    for (const s of parsed.sources) line(`Found ${s}`, "small muted");
    for (const w of parsed.warnings) line(w, "small err");
    if (!parsed.conversations.length) return line("No conversations found in these files.", "err");
    const total = parsed.conversations.length;
    const bar = h("progress", { max: total, value: 0 }) as HTMLProgressElement;
    const label = h("div", { class: "small muted" }, `Saving 0 / ${total} conversations…`);
    log.append(bar, label);
    const sum = { added: 0, updated: 0, unchanged: 0 };
    const t0 = performance.now();
    for (let i = 0; i < total; i += 25) {
      const r = (await call({ type: "upsert", conversations: parsed.conversations.slice(i, i + 25) })).report!;
      sum.added += r.added; sum.updated += r.updated; sum.unchanged += r.unchanged;
      bar.value = Math.min(i + 25, total);
      const rate = (performance.now() - t0) / bar.value;
      label.textContent = `Saving ${bar.value} / ${total} conversations · about ${Math.max(1, Math.ceil((rate * (total - bar.value)) / 1000))} s left`;
    }
    label.textContent = "";
    bar.remove();
    await refreshState();
    line(h("strong", { class: "okc" }, `Done: ${sum.added} new, ${sum.updated} updated, ${sum.unchanged} already up to date${parsed.skipped ? `, ${parsed.skipped} empty skipped` : ""}.`));
    line("You can search right away. Meaning-based search is added on-device in the background; the badge at the top shows progress.", "small muted");
    log.append(h("a", { href: "#" }, h("button", { class: "primary" }, "Start searching")));
  }
}

// ---------------------------------------------------------------- settings
async function settingsView(): Promise<void> {
  setNav("settings");
  const s = (await call({ type: "settings" })).settings!;
  const st = state!;
  const msg = h("p", { class: "small" });
  const say = (t: string, ok = true) => { msg.className = `small ${ok ? "okc" : "err"}`; msg.textContent = t; };
  const caps = ADAPTERS.map((a) => h("label", { class: "row" }, h("input", { type: "checkbox", checked: s.capture[a.platform], onchange: (e: Event) =>
    call({ type: "settings", set: { capture: { ...s.capture, [a.platform]: (e.target as HTMLInputElement).checked } } }) }), `${PLATFORMS[a.platform].label}${a.verified ? "" : " (beta)"}`));

  const protection = h("div", { class: "stack" });
  if (st.mode === "device") {
    const p = h("input", { type: "password", placeholder: "New passphrase (10+ characters)" }) as HTMLInputElement;
    protection.append(h("p", {}, "Encrypted on this device, no passphrase."), p, h("button", { onclick: async () => {
      try { const r = await call({ type: "switchMode", to: "passphrase", passphrase: p.value }); showRecovery(r.recoveryKey!, () => void route()); } catch (e) { say((e as Error).message, false); }
    } }, "Add a passphrase"));
  } else {
    const cur = h("input", { type: "password", placeholder: "Current passphrase" }) as HTMLInputElement;
    const nxt = h("input", { type: "password", placeholder: "New passphrase (10+ characters)" }) as HTMLInputElement;
    const lock = h("select", { onchange: (e: Event) => call({ type: "settings", set: { autoLockMinutes: Number((e.target as HTMLSelectElement).value) } }) },
      ...[[5, "5 minutes"], [15, "15 minutes"], [30, "30 minutes"], [120, "2 hours"], [0, "Only when the browser closes"]].map(([v, l]) => h("option", { value: String(v), selected: s.autoLockMinutes === v }, String(l))));
    protection.append(h("p", {}, "Encrypted with your passphrase."),
      h("div", { class: "row" }, h("span", { class: "small muted" }, "Auto-lock after inactivity:"), lock),
      h("div", { class: "row" }, h("button", { onclick: async () => { await call({ type: "lock" }); await route(); } }, "Lock now"),
        h("button", { onclick: async () => { if (confirm("Remove the passphrase? Your history stays encrypted on this device.")) { await call({ type: "switchMode", to: "device" }); await route(); } } }, "Remove passphrase")),
      cur, nxt, h("button", { onclick: async () => { try { await call({ type: "changePassphrase", current: cur.value, next: nxt.value }); say("Passphrase changed."); cur.value = nxt.value = ""; } catch (e) { say((e as Error).message, false); } } }, "Change passphrase"));
  }

  const bpw = h("input", { type: "password", placeholder: "Backup password (10+ characters)" }) as HTMLInputElement;
  const restoreInput = h("input", { type: "file", accept: ".json", hidden: true, onchange: async () => {
    const f = (restoreInput as HTMLInputElement).files?.[0];
    if (!f) return;
    try {
      const convs: Conversation[] = await decryptBackup(JSON.parse(await f.text()) as BackupFile, bpw.value);
      let added = 0;
      for (let i = 0; i < convs.length; i += 25) added += (await call({ type: "upsert", conversations: convs.slice(i, i + 25) })).report!.added;
      say(`Restored ${convs.length} conversations (${added} new).`);
      await refreshState();
    } catch (e) { say((e as Error).message, false); }
  } }) as HTMLInputElement;

  main.replaceChildren(h("div", { class: "stack" }, h("h1", {}, "Settings"),
    h("div", { class: "card stack" }, h("h2", {}, "Library"),
      h("p", {}, `${st.stats?.conversations ?? 0} conversations, ${st.stats?.messages ?? 0} messages, ${st.stats?.embedded ?? 0} indexed for smart search.`),
      h("p", { class: "small muted" }, Object.entries(st.stats?.byPlatform ?? {}).map(([p, n]) => `${PLATFORMS[p as Platform].label}: ${n}`).join(" · "))),
    h("div", { class: "card stack" }, h("h2", {}, "Save new chats automatically on"), ...caps,
      h("p", { class: "small muted" }, "Beta sites may miss messages when the site changes its layout. Imports always work.")),
    h("div", { class: "card stack" }, h("h2", {}, "Protection"), protection),
    h("div", { class: "card stack" }, h("h2", {}, "Backup and export"), bpw,
      h("div", { class: "row" },
        h("button", { onclick: async () => {
          try {
            const all = (await call({ type: "exportAll" })).conversations!;
            download(`aegismem-backup-${new Date().toISOString().slice(0, 10)}.json`, JSON.stringify(await encryptBackup(all, bpw.value)), "application/json");
            say(`Encrypted backup of ${all.length} conversations downloaded.`);
          } catch (e) { say((e as Error).message, false); }
        } }, "Download encrypted backup"),
        h("button", { onclick: () => restoreInput.click() }, "Restore from backup…"), restoreInput,
        h("button", { onclick: async () => {
          const all = (await call({ type: "exportAll" })).conversations!;
          const files: Record<string, Uint8Array> = {};
          for (const c of all) files[`${c.platform}/${c.updatedAt.slice(0, 10)} ${c.title.replace(/[^\w -]+/g, "").slice(0, 60) || c.nativeId}.md`] = strToU8(toMarkdown(c));
          download("aegismem-markdown.zip", zipSync(files), "application/zip");
        } }, "Export all as Markdown (.zip)"))),
    h("div", { class: "card stack" }, h("h2", {}, "Delete"),
      h("div", { class: "row" },
        h("button", { class: "danger", onclick: async () => { if (confirm("Delete every saved conversation? This can't be undone.")) { await call({ type: "deleteAll" }); await route(); } } }, "Delete all conversations"),
        h("button", { class: "danger", onclick: async () => { if (confirm("Erase everything, including keys and settings, and start over?")) { await call({ type: "wipeEverything" }); await chrome.storage.local.clear(); setTimeout(() => { location.hash = "#welcome"; void route(); }, 400); } } }, "Erase everything"))),
    msg,
    h("div", { class: "card stack small muted" }, h("h2", {}, "Privacy"),
      h("p", {}, "No accounts, servers, analytics or telemetry. Extension pages are blocked by their security policy from connecting to the internet at all. Your chats are read from AI sites you enable, encrypted, and stored only in this browser. Text leaves your device only when you click Continue or Ask, and then only to the AI you picked."),
      h("p", {}, `Search model: all-MiniLM-L6-v2, on-device. Version ${chrome.runtime.getManifest().version}.`))));
}

// ---------------------------------------------------------------- wiring
let debounce: number | undefined;
q.addEventListener("input", () => {
  clearTimeout(debounce);
  debounce = window.setTimeout(() => {
    if (!location.hash || location.hash === "#" || location.hash === "#search") void searchView();
    else location.hash = "#";
  }, 160);
});
q.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && lastResults[0]) location.hash = `#c/${encodeURIComponent(lastResults[0].convId)}/${lastResults[0].best.msgIndex}`;
});
document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== q && !(document.activeElement instanceof HTMLInputElement)) { e.preventDefault(); q.focus(); }
});
window.addEventListener("hashchange", () => void route());
const params = new URLSearchParams(location.search);
if (params.get("q")) q.value = params.get("q")!;
void route();
