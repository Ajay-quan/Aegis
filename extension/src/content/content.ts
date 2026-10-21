/**
 * Runs on supported AI sites.
 *   capture  user messages are sent to the vault (only if the user enabled capture for this site)
 *   insert   the "AegisMem" button adds relevant memories to the prompt, visibly, on the user's click
 * Assistant replies and other page text are not captured.
 */
import { adapterFor } from "./adapters";
import { send } from "../messages";

const adapter = adapterFor(location.hostname);
const seen = new Set<string>();

const CONTEXT_HEADER = "Context from my personal memory (AegisMem).";
function capture(text: string): void {
  let t = text.trim();
  if (t.startsWith(CONTEXT_HEADER)) {
    const end = t.indexOf("\n\n");
    t = end < 0 ? "" : t.slice(end + 2).trim(); // never re-capture inserted memories
  }
  if (!adapter || !t || seen.has(t)) return;
  seen.add(t);
  send({ type: "capture", text: t, site: adapter.site, url: location.href }).catch(() => {});
}

function draftText(input: HTMLElement): string {
  return (input instanceof HTMLTextAreaElement ? input.value : input.innerText).trim();
}

// Path 2: capture what the user is sending when they press Enter, independent of how the site renders it.
document.addEventListener(
  "keydown",
  (e) => {
    if (!adapter || e.key !== "Enter" || e.shiftKey || e.isComposing) return;
    const input = (e.target as HTMLElement | null)?.closest?.(adapter.input) as HTMLElement | null;
    if (input) capture(draftText(input));
  },
  true,
);

function captureNew(): void {
  if (!adapter) return;
  for (const el of document.querySelectorAll<HTMLElement>(adapter.userMessage)) capture(el.innerText);
}

let timer: number | undefined;
function schedule(): void {
  clearTimeout(timer);
  timer = window.setTimeout(captureNew, 800);
}

function toast(msg: string): void {
  const t = document.createElement("div");
  t.textContent = msg;
  t.style.cssText =
    "position:fixed;right:20px;bottom:76px;z-index:2147483647;background:#1f2937;color:#fff;padding:8px 12px;" +
    "border-radius:8px;font:13px system-ui,sans-serif;box-shadow:0 4px 12px rgba(0,0,0,.25)";
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3500);
}

async function insertMemories(): Promise<void> {
  if (!adapter) return;
  const input = document.querySelector<HTMLElement>(adapter.input);
  if (!input) return toast("AegisMem: couldn't find the message box on this page.");
  const draft = draftText(input);
  if (!draft) return toast("AegisMem: type your message first, then click to add relevant memories.");
  const res = await send({ type: "context", query: draft });
  if (!res.ok) return toast(res.error === "locked" ? "AegisMem is locked. Open the side panel to unlock." : `AegisMem: ${res.error}`);
  if (!res.context) return toast("AegisMem: no relevant memories for this message.");
  input.focus();
  const full = `${res.context}\n\n${draft}`;
  if (input instanceof HTMLTextAreaElement) {
    input.value = full;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  } else {
    document.execCommand("selectAll");
    document.execCommand("insertText", false, full);
  }
  toast("AegisMem: memories added. Review them before sending.");
}

function button(): void {
  if (document.getElementById("aegismem-btn")) return;
  const b = document.createElement("button");
  b.id = "aegismem-btn";
  b.type = "button";
  b.textContent = "＋ Memories";
  b.title = "AegisMem: add relevant memories to this message";
  b.style.cssText =
    "position:fixed;right:20px;bottom:24px;z-index:2147483647;border:0;border-radius:999px;padding:8px 14px;" +
    "background:#4f46e5;color:#fff;font:600 13px system-ui,sans-serif;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,.25)";
  b.addEventListener("click", () => void insertMemories());
  document.body.appendChild(b);
}

if (adapter) {
  button();
  captureNew();
  new MutationObserver(schedule).observe(document.body, { childList: true, subtree: true });
}
