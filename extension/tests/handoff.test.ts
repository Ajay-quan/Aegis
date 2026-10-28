import { describe, expect, it } from "vitest";
import { buildAsk, buildContinuation, toMarkdown } from "../src/core/handoff";
import type { Conversation } from "../src/core/types";

const long = (n: number): Conversation => ({
  id: "chatgpt:x", platform: "chatgpt", nativeId: "x", title: "Kitchen remodel", createdAt: "2026-04-01T00:00:00Z", updatedAt: "2026-04-03T00:00:00Z", source: "import",
  messages: Array.from({ length: n }, (_, i) => ({ role: i % 2 ? "assistant" : "user", text: `Message ${i}. ${"detail ".repeat(i === 0 ? 20 : 120)}End of ${i}.` })) as Conversation["messages"],
});

describe("handoff", () => {
  it("keeps goal + latest turns verbatim, compresses the middle, respects the budget", () => {
    const t = buildContinuation(long(60), 8000);
    expect(t.length).toBeLessThanOrEqual(8000);
    expect(t).toContain("## Original request\nMessage 0.");
    expect(t).toContain("End of 59.");
    expect(t).toContain("End of 56.");
    expect(t).toMatch(/earlier messages? omitted/);
    expect(t).toContain('titled "Kitchen remodel"');
  });

  it("short conversations are included whole", () => {
    const t = buildContinuation(long(3));
    expect(t).toContain("End of 0.");
    expect(t).not.toContain("omitted");
  });

  it("ask prompt numbers excerpts and stays within budget", () => {
    const ex = Array.from({ length: 20 }, (_, i) => ({ platform: "claude" as const, title: `T${i}`, date: "2026-01-01", text: "x".repeat(1500) }));
    const t = buildAsk("What did I decide about the lease?", ex, 6000);
    expect(t.length).toBeLessThanOrEqual(6000);
    expect(t).toContain("[1] Claude · 2026-01-01");
    expect(t).toContain("What did I decide about the lease?");
  });

  it("markdown export", () => {
    expect(toMarkdown(long(2))).toMatch(/^# Kitchen remodel/);
  });
});
