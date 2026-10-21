import { CATEGORIES, type Category } from "../core/analyze";
import type { Memory } from "../core/vault";
import { send, type Settings } from "../messages";

const app = document.getElementById("app")!;
const lockstate = document.getElementById("lockstate")!;
let tab: "memories" | "review" | "settings" = "memories";
let filter: Category | "" = "";

function el<K extends keyof HTMLElementTagNameMap>(tag: K, props: Partial<HTMLElementTagNameMap[K]> = {}, ...kids: (Node | string)[]): HTMLElementTagNameMap[K] {
  const e = Object.assign(document.createElement(tag), props);
  for (const k of kids) e.append(k); // strings become text nodes: no HTML injection
  return e;
}

function errorLine(): HTMLParagraphElement {
  return el("p", { className: "err" });
}

async function render(): Promise<void> {
  const r = await send({ type: "status" });
  if (!r.ok || !r.status) return void app.replaceChildren(el("p", { className: "err" }, "Extension error"));
  lockstate.textContent = r.status.unlocked ? "Unlocked" : "Locked";
  if (!r.status.exists) return setupView();
  if (!r.status.unlocked) return unlockView();
  return mainView(r.status.settings);
}

function setupView(): void {
  const p1 = el("input", { type: "password", placeholder: "Passphrase (10+ characters)" });
  const p2 = el("input", { type: "password", placeholder: "Repeat passphrase" });
  const err = errorLine();
  const go = el("button", { className: "primary", textContent: "Create my private vault" });
  go.onclick = async () => {
    if (p1.value !== p2.value) return void (err.textContent = "Passphrases don't match.");
    go.disabled = true;
    go.textContent = "Creating (a few seconds)…";
    const r = await send({ type: "setup", passphrase: p1.value });
    if (!r.ok) {
      go.disabled = false;
      go.textContent = "Create my private vault";
      return void (err.textContent = r.error);
    }
    recoveryView(r.recoveryKey!);
  };
  app.replaceChildren(
    el("h2", {}, "Set up your private memory"),
    el("p", { className: "hint" }, "Everything is encrypted on this device with your passphrase. Nobody else, including AegisMem, can read it. If you lose both your passphrase and recovery key, your memory cannot be recovered."),
    p1, el("div", { className: "row" }), p2, el("div", { className: "row" }, go), err,
  );
}

function recoveryView(key: string): void {
  const ok = el("button", { className: "primary", textContent: "I saved it, continue" });
  ok.onclick = () => void render();
  const copy = el("button", { textContent: "Copy" });
  copy.onclick = () => void navigator.clipboard.writeText(key);
  app.replaceChildren(
    el("h2", {}, "Save your recovery key"),
    el("p", { className: "hint" }, "This is shown only once. Store it in a password manager. It's the only way back in if you forget your passphrase."),
    el("div", { className: "key" }, key),
    el("div", { className: "row" }, copy, ok),
  );
}

function unlockView(): void {
  const p = el("input", { type: "password", placeholder: "Passphrase" });
  const err = errorLine();
  const go = el("button", { className: "primary", textContent: "Unlock" });
  const submit = async () => {
    go.disabled = true;
    const r = await send({ type: "unlock", passphrase: p.value });
    go.disabled = false;
    if (!r.ok) return void (err.textContent = r.error);
    void render();
  };
  go.onclick = submit;
  p.onkeydown = (e) => e.key === "Enter" && void submit();
  const forgot = el("button", { textContent: "Forgot passphrase? Use recovery key" });
  forgot.onclick = recoverView;
  app.replaceChildren(el("h2", {}, "Unlock AegisMem"), p, el("div", { className: "row" }, go, forgot), err);
  p.focus();
}

function recoverView(): void {
  const k = el("input", { placeholder: "Recovery key" });
  const p = el("input", { type: "password", placeholder: "New passphrase (10+ characters)" });
  const err = errorLine();
  const go = el("button", { className: "primary", textContent: "Recover" });
  go.onclick = async () => {
    const r = await send({ type: "recover", recoveryKey: k.value, newPassphrase: p.value });
    if (!r.ok) return void (err.textContent = r.error);
    void render();
  };
  const back = el("button", { textContent: "Back" });
  back.onclick = unlockView;
  app.replaceChildren(el("h2", {}, "Recover with your key"), k, el("div", { className: "row" }), p, el("div", { className: "row" }, go, back), err);
}

async function mainView(settings: Settings): Promise<void> {
  const r = await send({ type: "list" });
  const all = (r.ok && r.memories) || [];
  const pending = all.filter((m) => m.status === "pending");
  const tabs = el("div", { className: "tabs" });
  for (const [id, label] of [["memories", `Memories (${all.length - pending.length})`], ["review", `Review (${pending.length})`], ["settings", "Settings"]] as const) {
    const b = el("button", { textContent: label });
    b.setAttribute("aria-selected", String(tab === id));
    b.onclick = () => ((tab = id), void render());
    tabs.append(b);
  }
  const lock = el("button", { textContent: "Lock" });
  lock.onclick = async () => (await send({ type: "lock" }), void render());
  tabs.append(lock);
  const body =
    tab === "memories" ? memoriesTab(all.filter((m) => m.status === "active"), settings)
    : tab === "review" ? reviewTab(pending)
    : settingsTab(settings);
  app.replaceChildren(tabs, body);
}

function memoriesTab(ms: Memory[], settings: Settings): HTMLElement {
  const wrap = el("div");
  if (!Object.values(settings.capture).some(Boolean)) {
    wrap.append(el("p", { className: "hint" }, "Capture is off on every site. Turn it on in Settings to start remembering what you tell your AIs."));
  }
  const add = el("textarea", { placeholder: "Add a memory yourself, e.g. \"I'm allergic to peanuts\"" });
  const addBtn = el("button", { className: "primary", textContent: "Add" });
  addBtn.onclick = async () => {
    if (!add.value.trim()) return;
    await send({ type: "add", text: add.value });
    void render();
  };
  const sel = el("select");
  sel.append(el("option", { value: "", textContent: "All categories" }));
  for (const c of CATEGORIES) sel.append(el("option", { value: c, textContent: c, selected: c === filter }));
  sel.onchange = () => ((filter = sel.value as Category | ""), void render());
  wrap.append(add, el("div", { className: "row" }, addBtn, sel));
  const shown = ms.filter((m) => !filter || m.category === filter);
  if (!shown.length) wrap.append(el("p", { className: "hint" }, "No memories yet."));
  for (const m of shown) wrap.append(card(m));
  return wrap;
}

function card(m: Memory): HTMLElement {
  const text = el("div", {}, m.text);
  const cat = el("select");
  for (const c of CATEGORIES) cat.append(el("option", { value: c, textContent: c, selected: c === m.category }));
  cat.style.width = "auto";
  cat.onchange = async () => void (await send({ type: "category", id: m.id, category: cat.value as Category }));
  const edit = el("button", { textContent: "Edit" });
  edit.onclick = () => {
    const t = el("textarea", { value: m.text });
    const save = el("button", { className: "primary", textContent: "Save" });
    save.onclick = async () => (await send({ type: "edit", id: m.id, text: t.value }), void render());
    text.replaceWith(el("div", {}, t, el("div", { className: "row" }, save)));
  };
  const del = el("button", { className: "danger", textContent: "Delete" });
  del.onclick = async () => {
    const r = await send({ type: "forget", id: m.id });
    if (r.ok && r.receipt?.verified) void render();
  };
  const badges = el("div");
  if (m.updates) badges.append(el("span", { className: "badge" }, "updates an earlier memory"));
  if (m.updatedBy) badges.append(el("span", { className: "badge" }, "has a newer version"));
  if (m.redactions.length) badges.append(el("span", { className: "badge" }, `redacted: ${m.redactions.join(", ")}`));
  return el("div", { className: "card" }, text, badges,
    el("div", { className: "meta" }, `${new Date(m.createdAt).toLocaleString()} · from ${m.source.site}`),
    el("div", { className: "actions" }, cat, edit, del));
}

function reviewTab(ms: Memory[]): HTMLElement {
  const wrap = el("div", {}, el("p", { className: "hint" }, "These look like instructions aimed at an AI, not facts about you. They are never used until you approve them."));
  if (!ms.length) wrap.append(el("p", { className: "hint" }, "Nothing to review."));
  for (const m of ms) {
    const ok = el("button", { textContent: "Keep as memory" });
    ok.onclick = async () => (await send({ type: "approve", id: m.id }), void render());
    const no = el("button", { className: "danger", textContent: "Discard" });
    no.onclick = async () => (await send({ type: "forget", id: m.id }), void render());
    wrap.append(el("div", { className: "card" }, el("div", {}, m.text),
      el("div", { className: "meta" }, `Flagged: ${m.flags.join("; ")} · from ${m.source.site}`),
      el("div", { className: "actions" }, ok, no)));
  }
  return wrap;
}

function settingsTab(s: Settings): HTMLElement {
  const wrap = el("div", {}, el("h2", {}, "Capture"), el("p", { className: "hint" }, "When on, messages you send on that site are scanned on this device and memorable facts about you are saved, encrypted. AI replies are not saved."));
  for (const site of Object.keys(s.capture)) {
    const box = el("input", { type: "checkbox", checked: s.capture[site] });
    box.style.width = "auto";
    box.onchange = async () => void (await send({ type: "settings", set: { capture: { [site]: box.checked } } }));
    wrap.append(el("label", { className: "row" }, box, site));
  }
  const exp = el("button", { textContent: "Export (unencrypted JSON)" });
  exp.onclick = async () => {
    const r = await send({ type: "export" });
    if (!r.ok || !r.json) return;
    const a = el("a", { href: URL.createObjectURL(new Blob([r.json], { type: "application/json" })), download: "aegismem-export.json" });
    a.click();
  };
  const wipe = el("button", { className: "danger", textContent: "Delete all memories" });
  wipe.onclick = async () => {
    if (!confirm("Permanently delete every memory on this device?")) return;
    await send({ type: "forgetAll" });
    void render();
  };
  wrap.append(el("h2", {}, "Your data"), el("div", { className: "row" }, exp, wipe),
    el("p", { className: "hint" }, "When you click ＋ Memories on a site, the memories you add become part of your message and are sent to that AI provider. Review them before sending."));
  return wrap;
}

chrome.runtime.onMessage.addListener((m) => {
  if (m?.type === "changed") void render();
});
void render();
