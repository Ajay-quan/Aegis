/** Quick search (toolbar button or Ctrl/Cmd+Shift+K). Results open in the full app. */
import type { Result } from "../core/library";
import { PLATFORMS } from "../core/types";
import { send } from "../protocol";
import { h, highlighted, when } from "./dom";

const q = document.getElementById("q") as HTMLInputElement;
const out = document.getElementById("out")!;
let results: Result[] = [];
let sel = 0;

const open = (hash: string) => void chrome.tabs.create({ url: chrome.runtime.getURL(`app.html${hash}`) }).then(() => window.close());

function render(): void {
  out.replaceChildren(...results.slice(0, 7).map((r, i) => h("a", { class: "card result", href: "#", style: i === sel ? "border-color:var(--accent)" : "",
    onclick: (e: Event) => { e.preventDefault(); open(`#c/${encodeURIComponent(r.convId)}/${r.best.msgIndex}`); } },
  h("span", { class: "badge" }, h("span", { class: `dot ${r.platform}` }), `${PLATFORMS[r.platform].label} · ${when(r.updatedAt)}`),
  h("h3", {}, r.title || "Untitled"),
  r.best.role !== "title" ? h("div", { class: "snip small" }, highlighted(r.best.snippet)) : null)));
}

async function init(): Promise<void> {
  const s = await send({ type: "state" });
  if (!s.ok || !s.state?.exists || !s.state.unlocked) {
    out.replaceChildren(h("div", { class: "card stack" }, h("p", {}, !s.ok || !s.state?.exists ? "Set up AegisMem to start." : "AegisMem is locked."),
      h("button", { class: "primary", onclick: () => open("") }, "Open AegisMem")));
    q.disabled = true;
    return;
  }
  out.replaceChildren(h("p", { class: "muted small" }, `Search ${s.state.stats?.conversations ?? 0} conversations. Enter opens the top result; ↑↓ to choose.`));
}

let t: number | undefined;
q.addEventListener("input", () => {
  clearTimeout(t);
  t = window.setTimeout(async () => {
    const query = q.value.trim();
    if (!query) return void init();
    const r = await send({ type: "search", query, opts: { limit: 7 } });
    if (q.value.trim() !== query) return;
    results = r.ok ? r.results ?? [] : [];
    sel = 0;
    if (!results.length) out.replaceChildren(h("p", { class: "muted small" }, "No matches."));
    else render();
  }, 120);
});
q.addEventListener("keydown", (e) => {
  if (e.key === "ArrowDown") { sel = Math.min(sel + 1, Math.min(results.length, 7) - 1); render(); e.preventDefault(); }
  if (e.key === "ArrowUp") { sel = Math.max(sel - 1, 0); render(); e.preventDefault(); }
  if (e.key === "Enter" && results[sel]) open(`#c/${encodeURIComponent(results[sel].convId)}/${results[sel].best.msgIndex}`);
});
document.getElementById("all")!.addEventListener("click", (e) => { e.preventDefault(); open(q.value.trim() ? `?q=${encodeURIComponent(q.value.trim())}` : ""); });
void init();
