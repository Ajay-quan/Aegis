import "fake-indexeddb/auto";
import { beforeEach, describe, expect, it } from "vitest";
import { db } from "../src/core/db";
import { Library } from "../src/core/library";
import { chunkText, snippet } from "../src/core/index";
import type { Conversation } from "../src/core/types";

const conv = (id: string, title: string, msgs: [string, string][], at = "2026-05-01T00:00:00Z"): Conversation => ({
  id: `chatgpt:${id}`, platform: "chatgpt", nativeId: id, title, createdAt: at, updatedAt: at, source: "import",
  messages: msgs.map(([role, text]) => ({ role: role as "user" | "assistant", text })),
});

beforeEach(async () => {
  await db.wipe();
});

describe("library", () => {
  it("device mode: stores only ciphertext and reopens without a passphrase", async () => {
    const lib = new Library();
    await lib.setupDevice();
    await lib.upsert([conv("1", "Rent increase", [["user", "Can my landlord raise rent mid-lease in Colorado?"], ["assistant", "Generally not during a fixed-term lease."]])]);
    const raw = JSON.stringify(await db.all());
    expect(raw).not.toMatch(/landlord|Colorado|Rent increase/);
    const again = new Library();
    expect(await again.init()).toBe("device");
    expect((await again.search("landlord rent"))[0].convId).toBe("chatgpt:1");
  });

  it("passphrase mode: locked until unlocked; wrong passphrase rejected; recovery works", async () => {
    const lib = new Library();
    const rk = await lib.setupPassphrase("correct horse battery", 1000);
    await lib.upsert([conv("1", "Trip", [["user", "Plan 4 days in Kyoto"]])]);
    lib.lock();
    await expect(lib.search("Kyoto")).rejects.toThrow(/locked/);
    await expect(lib.unlock("nope nope nope")).rejects.toThrow(/Wrong passphrase/);
    await lib.recover(rk, "brand new passphrase");
    expect((await lib.search("Kyoto"))).toHaveLength(1);
  });

  it("switching modes re-encrypts everything and keeps data", async () => {
    const lib = new Library();
    await lib.setupDevice();
    await lib.upsert([conv("1", "Chess", [["user", "Best opening against e4?"]])]);
    const rk = await lib.switchMode("passphrase", "switch passphrase 1");
    expect(rk).toMatch(/^[0-9a-f-]+$/);
    const other = new Library();
    expect(await other.init()).toBe("passphrase");
    await other.unlock("switch passphrase 1");
    expect((await other.search("opening e4"))[0].title).toBe("Chess");
  });

  it("re-import of unchanged conversations is skipped; changed ones update", async () => {
    const lib = new Library();
    await lib.setupDevice();
    const c = conv("1", "A", [["user", "first message here"]]);
    expect(await lib.upsert([c])).toEqual({ added: 1, updated: 0, unchanged: 0 });
    expect(await lib.upsert([c])).toEqual({ added: 0, updated: 0, unchanged: 1 });
    const c2 = { ...c, messages: [...c.messages, { role: "assistant" as const, text: "a reply" }] };
    expect(await lib.upsert([c2])).toEqual({ added: 0, updated: 1, unchanged: 0 });
    expect(lib.stats().messages).toBe(2);
  });

  it("masks secrets before storing", async () => {
    const lib = new Library();
    await lib.setupDevice();
    await lib.upsert([conv("1", "Keys", [["user", "my key is sk-abcdefghijklmnopqrstuv and card 4111 1111 1111 1111"]])]);
    const t = lib.get("chatgpt:1")!.messages[0].text;
    expect(t).not.toMatch(/sk-abc|4111/);
    expect(t).toMatch(/\[SECRET\].*\[CARD\]/);
  });

  it("filters by platform and date, ranks by best chunk, deletes verifiably", async () => {
    const lib = new Library();
    await lib.setupDevice();
    await lib.upsert([
      conv("1", "Sourdough", [["user", "My sourdough starter smells like acetone"]], "2026-01-01T00:00:00Z"),
      { ...conv("2", "Bread", [["user", "sourdough hydration for a beginner"]], "2026-06-01T00:00:00Z"), id: "claude:2", platform: "claude" },
    ]);
    expect((await lib.search("sourdough")).length).toBe(2);
    expect((await lib.search("sourdough", { platforms: ["claude"] })).map((r) => r.convId)).toEqual(["claude:2"]);
    expect((await lib.search("sourdough", { from: Date.parse("2026-03-01") })).map((r) => r.convId)).toEqual(["claude:2"]);
    expect(await lib.remove("chatgpt:1")).toBe(true);
    expect((await lib.search("acetone")).length).toBe(0);
  });
});

describe("chunking and snippets", () => {
  it("splits long text with overlap and never loses the end", () => {
    const text = Array.from({ length: 60 }, (_, i) => `Sentence number ${i} talks about topic ${i}.`).join(" ");
    const cs = chunkText(text, 400, 80);
    expect(cs.length).toBeGreaterThan(3);
    expect(cs.every((c) => c.length <= 400)).toBe(true);
    expect(cs[cs.length - 1]).toContain("topic 59.");
  });

  it("snippet centres on the first match and marks highlights", () => {
    const s = snippet("x ".repeat(300) + "the landlord raised the rent " + "y ".repeat(300), "landlord rent");
    expect(s.text).toContain("landlord");
    expect(s.ranges.length).toBe(2);
    expect(s.text.slice(s.ranges[0][0], s.ranges[0][1]).toLowerCase()).toBe("landlord");
  });
});

import { decryptBackup, encryptBackup } from "../src/core/backup";
describe("backup", () => {
  it("round-trips with the right password and rejects a wrong one", async () => {
    const cs = [conv("9", "Backup me", [["user", "remember the blue notebook"]])];
    const f = await encryptBackup(cs, "backup password 1", 1000);
    expect(JSON.stringify(f)).not.toContain("blue notebook");
    expect((await decryptBackup(f, "backup password 1"))[0].title).toBe("Backup me");
    await expect(decryptBackup(f, "wrong password!!")).rejects.toThrow(/Wrong password/);
  });
});

import { topK } from "../src/core/index";
describe("topK", () => {
  it("matches a full sort", () => {
    let seed = 5;
    const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
    const xs: [number, number][] = Array.from({ length: 5000 }, (_, i) => [i, rnd()]);
    const want = [...xs].sort((a, b) => b[1] - a[1]).slice(0, 37);
    expect(topK(xs, 37)).toEqual(want);
    expect(topK(xs.slice(0, 10), 37)).toHaveLength(10);
  });
});
