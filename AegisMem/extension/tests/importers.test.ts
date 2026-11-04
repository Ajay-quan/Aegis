import { describe, expect, it } from "vitest";
import { strToU8, zipSync } from "fflate";
import { parseChatGPT } from "../src/importers/chatgpt";
import { parseClaude } from "../src/importers/claude";
import { parseGemini } from "../src/importers/gemini";
import { detectAndParse } from "../src/importers/detect";

const gptConv = {
  id: "c-1", conversation_id: "c-1", title: "Lease question", create_time: 1717000000.5, update_time: 1717000500,
  current_node: "a2",
  mapping: {
    root: { id: "root", parent: null, children: ["sys"], message: null },
    sys: { id: "sys", parent: "root", children: ["u1"], message: { author: { role: "system" }, content: { content_type: "text", parts: [""] } } },
    u1: { id: "u1", parent: "sys", children: ["a1", "a2"], message: { author: { role: "user" }, create_time: 1717000001, content: { content_type: "text", parts: ["Can my landlord raise rent mid-lease?"] } } },
    a1: { id: "a1", parent: "u1", children: [], message: { author: { role: "assistant" }, content: { content_type: "text", parts: ["OLD BRANCH answer"] } } },
    a2: { id: "a2", parent: "u1", children: [], message: { author: { role: "assistant" }, recipient: "all", create_time: 1717000002, content: { content_type: "multimodal_text", parts: ["Usually not, unless the lease allows it.", { content_type: "image_asset_pointer" }] } } },
  },
};

describe("ChatGPT import", () => {
  it("follows the active branch from current_node and skips system, hidden and tool messages", () => {
    const r = parseChatGPT([gptConv]);
    const c = r.conversations[0];
    expect(c.id).toBe("chatgpt:c-1");
    expect(c.messages.map((m) => m.role)).toEqual(["user", "assistant"]);
    expect(c.messages[1].text).toContain("Usually not");
    expect(c.messages[1].text).toContain("[image]");
    expect(JSON.stringify(c)).not.toContain("OLD BRANCH");
    expect(c.createdAt).toBe(new Date(1717000000500).toISOString());
  });

  it("skips conversations without usable messages", () => {
    const r = parseChatGPT([{ id: "x", mapping: { root: { parent: null, message: null } } }]);
    expect(r.conversations).toHaveLength(0);
    expect(r.skipped).toBe(1);
  });

  it("falls back to the latest leaf when current_node is missing", () => {
    const { current_node: _omit, ...noPtr } = gptConv;
    const c = parseChatGPT([noPtr]).conversations[0];
    expect(c.messages[1].text).toContain("Usually not");
  });
});

describe("Claude import", () => {
  it("maps human/assistant, prefers text blocks, skips thinking", () => {
    const r = parseClaude([{
      uuid: "u-9", name: "", created_at: "2026-01-02T03:04:05Z", updated_at: "2026-01-02T04:00:00Z",
      chat_messages: [
        { sender: "human", text: "Draft a cover letter for a data role", content: [{ type: "text", text: "Draft a cover letter for a data role" }], created_at: "2026-01-02T03:04:05Z" },
        { sender: "assistant", text: "", content: [{ type: "thinking", text: "secret reasoning" }, { type: "text", text: "Dear hiring manager," }] },
      ],
    }]);
    const c = r.conversations[0];
    expect(c.title).toBe("Draft a cover letter for a data role");
    expect(c.messages.map((m) => m.text)).toEqual(["Draft a cover letter for a data role", "Dear hiring manager,"]);
    expect(JSON.stringify(c)).not.toContain("secret reasoning");
  });
});

describe("Gemini import", () => {
  const entries = [
    { header: "Gemini Apps", title: "Prompted best hikes near Denver", titleUrl: "https://gemini.google.com/app/abc123def", time: "2026-03-01T10:00:00Z", products: ["Gemini Apps"], safeHtmlItem: [{ html: "<p>Try <b>Mount Falcon</b></p>" }] },
    { header: "Gemini", title: "Used Gemini Apps", titleUrl: "https://gemini.google.com/app/abc123def", time: "2026-03-01T10:05:00Z", details: [{ name: "Request", value: "Which is easiest?" }, { name: "Response", value: "Red Rocks trail" }] },
    { header: "Gemini", title: "Used Gemini Apps", titleUrl: "https://gemini.google.com/app/zzz999yyy", time: "2026-03-02T09:00:00Z", userInteractions: [{ userInteraction: { request: JSON.stringify({ text: "Translate hola" }), response: "" } }] },
    { header: "Search", title: "Searched for cats", time: "2026-03-02T09:00:00Z" },
  ];
  it("handles all three variants, groups by conversation id, ignores non-Gemini activity", () => {
    const r = parseGemini(entries);
    expect(r.conversations).toHaveLength(2);
    const a = r.conversations.find((c) => c.nativeId === "abc123def")!;
    expect(a.messages.map((m) => m.text)).toEqual(["best hikes near Denver", "Try Mount Falcon", "Which is easiest?", "Red Rocks trail"]);
    expect(r.warnings.join()).toMatch(/1 prompts had no response/);
  });
});

describe("file detection", () => {
  it("reads split ChatGPT files and a Claude export inside zips, and dedupes repeats", () => {
    const gptZip = zipSync({ "conversations-0.json": strToU8(JSON.stringify([gptConv])), "conversations-1.json": strToU8(JSON.stringify([gptConv])), "chat.html": strToU8("<html>") });
    const claudeZip = zipSync({ "data/conversations.json": strToU8(JSON.stringify([{ uuid: "u1", name: "Hi", chat_messages: [{ sender: "human", text: "hello there" }] }])), "data/users.json": strToU8("[]") });
    const r = detectAndParse([{ name: "chatgpt.zip", bytes: gptZip }, { name: "claude.zip", bytes: claudeZip }, { name: "notes.json", bytes: strToU8('{"a":1}') }]);
    expect(r.conversations.map((c) => c.id).sort()).toEqual(["chatgpt:c-1", "claude:u1"]);
    expect(r.sources).toHaveLength(3);
    expect(r.warnings.join()).toMatch(/notes\.json: not a recognised/);
  });
});
