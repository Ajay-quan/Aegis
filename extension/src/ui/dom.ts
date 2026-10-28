/** Tiny DOM helpers. Chat text is only ever inserted as text nodes (no innerHTML), so it can't inject markup. */
import type { Snippet } from "../core/index";

type Kid = Node | string | null | undefined | false;

export function h<K extends keyof HTMLElementTagNameMap>(tag: K, props: Record<string, unknown> = {}, ...kids: Kid[]): HTMLElementTagNameMap[K] {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v as EventListener);
    else if (k === "class") e.className = String(v);
    else if (k === "style") e.style.cssText = String(v); // CSSOM: allowed under our strict CSP (style attributes are not)
    else if (k in e && typeof v !== "string") (e as unknown as Record<string, unknown>)[k] = v;
    else e.setAttribute(k, String(v));
  }
  for (const c of kids) if (c !== null && c !== undefined && c !== false) e.append(c);
  return e;
}

export function highlighted(s: Snippet): DocumentFragment {
  const f = document.createDocumentFragment();
  let i = 0;
  for (const [a, b] of s.ranges) {
    if (a > i) f.append(s.text.slice(i, a));
    f.append(h("mark", {}, s.text.slice(a, b)));
    i = b;
  }
  f.append(s.text.slice(i));
  return f;
}

export function when(iso: string): string {
  const d = new Date(iso);
  const days = (Date.now() - d.getTime()) / 86_400_000;
  if (days < 1 && days >= 0) return d.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  if (days < 7 && days >= 0) return d.toLocaleDateString([], { weekday: "short" });
  return d.toLocaleDateString([], { year: "numeric", month: "short", day: "numeric" });
}

export function download(name: string, data: string | Uint8Array, type: string): void {
  const url = URL.createObjectURL(new Blob([data as BlobPart], { type }));
  const a = h("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}
