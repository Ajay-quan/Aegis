/**
 * Gemini via Google Takeout → My Activity (JSON) → Gemini Apps → MyActivity.json.
 * One entry per prompt/response exchange. Known variants (detected per entry):
 *   A  details: [{ name: "Request"|"Response", value }]
 *   B  userInteractions: [{ userInteraction: { request: "<json>", response: "<json>" } }]
 *   C  title "Prompted <prompt>" + safeHtmlItem: [{ html: "<response html>" }]
 * Entries are grouped into conversations by the id in titleUrl (/app/<id>); entries without an id are
 * grouped by calendar day. Google truncates or omits some responses; that loss is reported, not hidden.
 */
import { convId, type Conversation, type Message } from "../core/types";
import { iso, stripHtml, titleFrom, type ImportResult } from "./common";

type Entry = {
  header?: string;
  title?: string;
  titleUrl?: string;
  time?: string;
  products?: string[];
  details?: { name?: string; value?: string }[];
  userInteractions?: { userInteraction?: { request?: string; response?: string } }[];
  safeHtmlItem?: { html?: string }[];
};

function deepText(x: unknown): string {
  if (typeof x === "string") {
    try {
      return deepText(JSON.parse(x));
    } catch {
      return x;
    }
  }
  if (Array.isArray(x)) return x.map(deepText).filter(Boolean).join("\n");
  if (x && typeof x === "object") {
    const o = x as Record<string, unknown>;
    for (const k of ["text", "prompt", "query", "content", "response", "value"]) if (k in o) return deepText(o[k]);
  }
  return "";
}

function exchange(e: Entry): { prompt: string; response: string } {
  if (Array.isArray(e.details) && e.details.length) {
    const get = (n: string) => e.details!.filter((d) => (d.name ?? "").toLowerCase().startsWith(n)).map((d) => d.value ?? "").join("\n");
    return { prompt: get("request").trim(), response: stripHtml(get("response")) };
  }
  if (Array.isArray(e.userInteractions) && e.userInteractions.length) {
    const ui = e.userInteractions.map((u) => u.userInteraction ?? {});
    return { prompt: ui.map((u) => deepText(u.request)).join("\n").trim(), response: stripHtml(ui.map((u) => deepText(u.response)).join("\n")) };
  }
  const prompt = (e.title ?? "").replace(/^Prompted\s+/i, "").trim();
  const response = stripHtml((e.safeHtmlItem ?? []).map((h) => h.html ?? "").join("\n"));
  return { prompt: /^used gemini apps$/i.test(prompt) ? "" : prompt, response };
}

export function looksLikeGemini(data: unknown): boolean {
  return Array.isArray(data) && data.some((e) => e && typeof e === "object" && /gemini|bard/i.test(`${(e as Entry).header ?? ""} ${((e as Entry).products ?? []).join(" ")}`));
}

export function parseGemini(data: unknown): ImportResult {
  const res: ImportResult = { conversations: [], skipped: 0, warnings: [] };
  if (!Array.isArray(data)) {
    res.warnings.push("Gemini export: expected MyActivity.json (a list of activity entries)");
    return res;
  }
  const groups = new Map<string, { at: string; prompt: string; response: string }[]>();
  let noResponse = 0;
  for (const raw of data as Entry[]) {
    if (!/gemini|bard/i.test(`${raw.header ?? ""} ${(raw.products ?? []).join(" ")}`)) continue;
    const at = iso(raw.time);
    const { prompt, response } = exchange(raw);
    if (!at || (!prompt && !response)) {
      res.skipped++;
      continue;
    }
    if (!response) noResponse++;
    const id = raw.titleUrl?.match(/\/app\/(?:c\/)?([A-Za-z0-9_-]{6,})/)?.[1] ?? `day-${at.slice(0, 10)}`;
    const g = groups.get(id) ?? [];
    g.push({ at, prompt, response });
    groups.set(id, g);
  }
  for (const [nativeId, ex] of groups) {
    ex.sort((a, b) => a.at.localeCompare(b.at));
    const messages: Message[] = [];
    for (const e of ex) {
      if (e.prompt) messages.push({ role: "user", text: e.prompt, at: e.at });
      if (e.response) messages.push({ role: "assistant", text: e.response, at: e.at });
    }
    const conv: Conversation = {
      id: convId("gemini", nativeId),
      platform: "gemini",
      nativeId,
      title: titleFrom(messages.find((m) => m.role === "user")?.text ?? messages[0].text),
      createdAt: ex[0].at,
      updatedAt: ex[ex.length - 1].at,
      messages,
      source: "import",
    };
    res.conversations.push(conv);
  }
  if (noResponse) res.warnings.push(`Gemini: ${noResponse} prompts had no response text in the export (Google omits or truncates some).`);
  return res;
}
