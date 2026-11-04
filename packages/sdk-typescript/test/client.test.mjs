// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Unit tests use a fake fetch; the live test runs only when AEGIS_API_URL/AEGIS_TOKEN are set.
import { test } from "node:test";
import assert from "node:assert/strict";
import { AegisClient, NotFoundError, ConflictError } from "../dist/index.js";

const json = (status, body, headers = {}) =>
  new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } });

test("rejects plain http to non-local hosts", () => {
  assert.throws(() => new AegisClient({ baseUrl: "http://api.example.com", token: "t" }));
});

test("never serializes the token", () => {
  const c = new AegisClient({ baseUrl: "https://api.example.com", token: "secret-token" });
  assert.ok(!JSON.stringify(c).includes("secret-token"));
});

test("maps error statuses to typed errors", async () => {
  const c = new AegisClient({ baseUrl: "https://x.test", token: "t",
    fetch: async () => json(404, { error: { code: "not_found", message: "run not found" } }) });
  await assert.rejects(c.getRun("run_x"), NotFoundError);
});

test("retries GET on 503 but not non-idempotent POST", async () => {
  let n = 0;
  const c = new AegisClient({ baseUrl: "https://x.test", token: "t", backoffMs: 1,
    fetch: async () => (++n < 3 ? json(503, {}) : json(200, { items: [] })) });
  assert.deepEqual(await c.listAgents(), []);
  assert.equal(n, 3);
  n = 0;
  const p = new AegisClient({ baseUrl: "https://x.test", token: "t", backoffMs: 1,
    fetch: async () => { n++; return json(503, { error: { code: "unavailable", message: "x" } }); } });
  await assert.rejects(p.cancelRun("run_x"));
  assert.equal(n, 1);
});

test("submitRun sends an idempotency key", async () => {
  let seen;
  const c = new AegisClient({ baseUrl: "https://x.test", token: "t",
    fetch: async (_u, init) => { seen = init.headers["Idempotency-Key"]; return json(409, { error: { code: "conflict", message: "x" } }); } });
  await assert.rejects(c.submitRun("agt_x", {}), ConflictError);
  assert.match(seen, /^sdk-/);
});

test("live: run lifecycle against local API", { skip: !process.env.AEGIS_TOKEN }, async () => {
  const c = new AegisClient({ baseUrl: process.env.AEGIS_API_URL ?? "http://127.0.0.1:8000", token: process.env.AEGIS_TOKEN });
  const project = await c.createProject(`ts-sdk-${Date.now()}`);
  const agent = await c.registerAgent(project.id, "ts-agent");
  await c.grantTool(agent.id, "calc.add", 0);
  const { id } = await c.submitRun(agent.id, { task: "add", mock_script: [{ tool: "calc.add", args: { a: 1, b: 2 } }, { final: "3" }] });
  const run = await c.waitForRun(id, 30_000);
  assert.equal(run.state, "SUCCEEDED");
  const events = await c.events(id);
  assert.ok(events.some((e) => e.event_type === "tool.execution_succeeded"));
  const bundle = await c.exportReceipt(id);
  assert.equal(bundle[0], 0x50); // "PK" zip header
  assert.equal((await c.replay(id)).decision_replay.status, "IDENTICAL");
});
