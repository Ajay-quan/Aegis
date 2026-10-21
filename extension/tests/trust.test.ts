import { describe, expect, it } from "vitest";
import { allowed, isTrusted } from "../src/trust";

const ID = "abcdefghijklmnop";
const ORIGIN = `chrome-extension://${ID}/`;

describe("message trust", () => {
  it("trusts only this extension's own pages", () => {
    expect(isTrusted({ id: ID, url: `${ORIGIN}panel.html` }, ID, ORIGIN)).toBe(true);
    expect(isTrusted({ id: ID, url: "https://chatgpt.com/c/1" }, ID, ORIGIN)).toBe(false); // content script
    expect(isTrusted({ id: "other", url: `${ORIGIN}panel.html` }, ID, ORIGIN)).toBe(false);
    expect(isTrusted({ id: ID }, ID, ORIGIN)).toBe(false);
  });

  it("content scripts can only capture, ask for context and read status", () => {
    for (const t of ["list", "export", "forget", "forgetAll", "edit", "approve", "settings", "unlock", "setup", "changePassphrase", "lock"]) {
      expect(allowed(t, false)).toBe(false);
    }
    for (const t of ["capture", "context", "status"]) expect(allowed(t, false)).toBe(true);
    expect(allowed("export", true)).toBe(true);
  });
});
