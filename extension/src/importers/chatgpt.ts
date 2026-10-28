/**
 * ChatGPT data export (Settings → Data controls → Export): conversations.json, or conversations-N.json
 * when split. Each conversation stores messages as a tree in `mapping` (edits and regenerations create
 * branches). The visible thread is the path from `current_node` up to the root.
 */
import { convId, type Conversation, type Message } from "../core/types";
import { iso, titleFrom, type ImportResult } from "./common";

type Node = { id?: string; parent?: string | null; children?: string[]; message?: Msg | null };
type Msg = {
  author?: { role?: string };
  create_time?: number | null;
  content?: { content_type?: string; parts?: unknown[]; text?: string };
  metadata?: { is_visually_hidden_from_conversation?: boolean };
  recipient?: string;
};

function textOf(m: Msg): string {
  const c = m.content ?? {};
  const type = c.content_type ?? "text";
  if (["thoughts", "reasoning_recap", "execution_output", "tether_browsing_display", "system_error", "user_editable_context"].includes(type)) return "";
  if (type === "code") return c.text ? "```\n" + c.text + "\n```" : "";
  const parts = (c.parts ?? []).map((p) => {
    if (typeof p === "string") return p;
    if (p && typeof p === "object") {
      const o = p as Record<string, unknown>;
      if (typeof o.text === "string") return o.text;
      if (o.content_type === "image_asset_pointer") return "[image]";
      if (o.content_type === "audio_transcription" && typeof o.text === "string") return o.text;
    }
    return "";
  });
  const t = parts.join("\n").trim();
  return t || (typeof c.text === "string" ? c.text.trim() : "");
}

function thread(mapping: Record<string, Node>, current?: string): Msg[] {
  const out: Msg[] = [];
  let id = current && mapping[current] ? current : undefined;
  if (!id) {
    // No pointer: take the leaf with the latest message time.
    let best = -Infinity;
    for (const [k, n] of Object.entries(mapping)) {
      if (n.children?.length) continue;
      const t = n.message?.create_time ?? 0;
      if (t >= best) {
        best = t;
        id = k;
      }
    }
  }
  const seen = new Set<string>();
  while (id && mapping[id] && !seen.has(id)) {
    seen.add(id);
    const n = mapping[id];
    if (n.message) out.push(n.message);
    id = n.parent ?? undefined;
  }
  return out.reverse();
}

export function looksLikeChatGPT(data: unknown): boolean {
  return Array.isArray(data) && data.some((c) => c && typeof c === "object" && "mapping" in c);
}

export function parseChatGPT(data: unknown): ImportResult {
  const res: ImportResult = { conversations: [], skipped: 0, warnings: [] };
  if (!Array.isArray(data)) {
    res.warnings.push("ChatGPT export: expected a list of conversations");
    return res;
  }
  for (const raw of data) {
    const c = raw as { id?: string; conversation_id?: string; title?: string; create_time?: number; update_time?: number; mapping?: Record<string, Node>; current_node?: string };
    const nativeId = c.conversation_id ?? c.id;
    if (!nativeId || !c.mapping) {
      res.skipped++;
      continue;
    }
    const messages: Message[] = [];
    for (const m of thread(c.mapping, c.current_node)) {
      const role = m.author?.role;
      if (role !== "user" && role !== "assistant") continue;
      if (m.metadata?.is_visually_hidden_from_conversation) continue;
      if (role === "assistant" && m.recipient && m.recipient !== "all") continue; // tool calls
      const text = textOf(m);
      if (!text) continue;
      messages.push({ role, text, at: iso(m.create_time ?? undefined) });
    }
    if (!messages.length) {
      res.skipped++;
      continue;
    }
    const created = iso(c.create_time) ?? messages[0].at ?? new Date(0).toISOString();
    res.conversations.push({
      id: convId("chatgpt", nativeId),
      platform: "chatgpt",
      nativeId,
      title: c.title?.trim() || titleFrom(messages[0].text),
      createdAt: created,
      updatedAt: iso(c.update_time) ?? messages[messages.length - 1].at ?? created,
      messages,
      source: "import",
    });
  }
  return res;
}
