/**
 * Claude data export (Settings → Privacy → Export data): conversations.json, a list of conversations
 * with `chat_messages` (sender "human" | "assistant"). Message text is in `text` and/or in `content`
 * blocks of type "text"; thinking/tool blocks are skipped.
 */
import { convId, type Conversation, type Message } from "../core/types";
import { iso, titleFrom, type ImportResult } from "./common";

type Block = { type?: string; text?: string };
type CMsg = { sender?: string; text?: string; content?: Block[]; created_at?: string };

function textOf(m: CMsg): string {
  const blocks = (m.content ?? []).filter((b) => b?.type === "text" && typeof b.text === "string").map((b) => b.text!.trim());
  const fromBlocks = blocks.join("\n\n").trim();
  return fromBlocks || (m.text ?? "").trim();
}

export function looksLikeClaude(data: unknown): boolean {
  return Array.isArray(data) && data.some((c) => c && typeof c === "object" && "chat_messages" in c);
}

export function parseClaude(data: unknown): ImportResult {
  const res: ImportResult = { conversations: [], skipped: 0, warnings: [] };
  if (!Array.isArray(data)) {
    res.warnings.push("Claude export: expected a list of conversations");
    return res;
  }
  for (const raw of data) {
    const c = raw as { uuid?: string; name?: string; created_at?: string; updated_at?: string; chat_messages?: CMsg[] };
    if (!c.uuid || !Array.isArray(c.chat_messages)) {
      res.skipped++;
      continue;
    }
    const messages: Message[] = [];
    for (const m of c.chat_messages) {
      const role = m.sender === "human" ? "user" : m.sender === "assistant" ? "assistant" : null;
      const text = textOf(m);
      if (!role || !text) continue;
      messages.push({ role, text, at: iso(m.created_at) });
    }
    if (!messages.length) {
      res.skipped++;
      continue;
    }
    const created = iso(c.created_at) ?? messages[0].at ?? new Date(0).toISOString();
    const conv: Conversation = {
      id: convId("claude", c.uuid),
      platform: "claude",
      nativeId: c.uuid,
      title: c.name?.trim() || titleFrom(messages[0].text),
      createdAt: created,
      updatedAt: iso(c.updated_at) ?? messages[messages.length - 1].at ?? created,
      messages,
      source: "import",
    };
    res.conversations.push(conv);
  }
  return res;
}
