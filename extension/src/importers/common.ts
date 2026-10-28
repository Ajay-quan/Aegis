import type { Conversation } from "../core/types";

export interface ImportResult {
  conversations: Conversation[];
  skipped: number; // conversations with no usable messages
  warnings: string[];
}

export function iso(x: unknown): string | undefined {
  if (typeof x === "number" && isFinite(x)) return new Date(x < 1e12 ? x * 1000 : x).toISOString(); // seconds or ms
  if (typeof x === "string" && x) {
    const t = Date.parse(x);
    if (!isNaN(t)) return new Date(t).toISOString();
  }
  return undefined;
}

export function stripHtml(html: string): string {
  return html
    .replace(/<(br|\/p|\/div|\/li|\/h\d)\s*\/?>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;|&#x27;/g, "'")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function titleFrom(text: string): string {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > 70 ? `${t.slice(0, 67)}…` : t || "Untitled";
}
