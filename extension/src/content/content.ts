/**
 * Runs on supported AI sites. Two jobs only:
 *   capture   after a reply finishes, send the visible conversation (both sides) to the library
 *   handoff   if this tab was opened by AegisMem to continue a chat, put the prepared text in the
 *             editor (never sends it; the user reviews and presses Enter)
 * Nothing from the library is ever shown on, or readable by, this page.
 */
import { adapterFor } from "./adapters";
import type { Message } from "../core/types";
import type { Request, Response } from "../protocol";

const send = (r: Request): Promise<Response> => chrome.runtime.sendMessage(r);
const a = adapterFor(location.hostname);
let lastSent = "";
let timer: number | undefined;

function collect(): Message[] {
  if (!a) return [];
  const out: Message[] = [];
  for (const el of document.querySelectorAll<HTMLElement>(`${a.user}, ${a.assistant}`)) {
    // skip elements nested inside another matched element (e.g. markdown inside a message wrapper)
    const parent = el.parentElement?.closest(`${a.user}, ${a.assistant}`);
    if (parent) continue;
    const text = el.innerText.trim();
    if (!text) continue;
    out.push({ role: el.matches(a.user) ? "user" : "assistant", text });
  }
  return out;
}

function capture(): void {
  if (!a) return;
  const id = location.pathname.match(a.idFromPath)?.[1];
  if (!id) return;
  if (document.querySelector(a.streaming)) return schedule(1500); // wait for the reply to finish
  const messages = collect();
  if (!messages.length) return;
  const key = `${id}|${messages.length}|${messages[messages.length - 1].text.length}`;
  if (key === lastSent) return;
  lastSent = key;
  const now = new Date().toISOString();
  void send({
    type: "captureConv",
    conversation: {
      id: `${a.platform}:${id}`, platform: a.platform, nativeId: id, title: a.title() || messages[0].text.slice(0, 70),
      createdAt: now, updatedAt: now, messages, source: "capture",
    },
  }).catch(() => {});
}

function schedule(ms = 1200): void {
  clearTimeout(timer);
  timer = window.setTimeout(capture, ms);
}

async function receiveHandoff(): Promise<void> {
  if (!a) return;
  // Claim the handoff only once the editor exists, so a login wall or interstitial page doesn't use it up.
  let input: HTMLElement | null = null;
  for (let i = 0; i < 120 && !(input = document.querySelector<HTMLElement>(a.input)); i++) await new Promise((res) => setTimeout(res, 250));
  if (!input) return;
  // Only a tab AegisMem just opened gets text; retry briefly while the tab id is being recorded.
  let r: Response | null = null;
  for (let i = 0; i < 8; i++) {
    r = await send({ type: "takeHandoff" }).catch(() => null);
    if (r?.ok && r.text) break;
    await new Promise((res) => setTimeout(res, 400));
  }
  if (!r?.ok || !r.text) return;
  input = document.querySelector<HTMLElement>(a.input) ?? input;
  input.focus();
  if (input instanceof HTMLTextAreaElement) {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")?.set;
    setter?.call(input, r.text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  } else {
    document.execCommand("selectAll");
    document.execCommand("insertText", false, r.text);
  }
}

if (a) {
  new MutationObserver(() => schedule()).observe(document.documentElement, { childList: true, subtree: true, characterData: true });
  schedule(2000);
  void receiveHandoff();
}
