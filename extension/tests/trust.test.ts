import { describe, expect, it } from "vitest";
import { allowed, isTrusted } from "../src/trust";

const ID = "abcdefghijklmnop";
const ORIGIN = `chrome-extension://${ID}/`;

describe("message trust", () => {
  it("trusts only this extension's own pages", () => {
    expect(isTrusted({ id: ID, url: `${ORIGIN}app.html` }, ID, ORIGIN)).toBe(true);
    expect(isTrusted({ id: ID, url: "https://chatgpt.com/c/1" }, ID, ORIGIN)).toBe(false);
    expect(isTrusted({ id: "other", url: `${ORIGIN}app.html` }, ID, ORIGIN)).toBe(false);
    expect(isTrusted({ id: ID }, ID, ORIGIN)).toBe(false);
  });

  it("AI-site pages can only submit captures and collect their own handoff; never read history", () => {
    for (const t of ["search", "get", "recent", "exportAll", "delete", "deleteAll", "state", "unlock", "settings", "handoff", "upsert", "switchMode", "wipeEverything"]) {
      expect(allowed(t, false)).toBe(false);
    }
    expect(allowed("captureConv", false)).toBe(true);
    expect(allowed("takeHandoff", false)).toBe(true);
    expect(allowed("search", true)).toBe(true);
  });
});
