// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Runs against the live compose stack. Requires AEGIS_TOKEN (see scripts/dev_bootstrap.py).
import { expect, test } from "@playwright/test";
import { AegisClient } from "@aegistrace/sdk";

const token = process.env.AEGIS_TOKEN ?? "";
const api = new AegisClient({ baseUrl: process.env.AEGIS_API_URL ?? "http://127.0.0.1:8000", token });

test.skip(!token, "AEGIS_TOKEN not set");

const sso = !!process.env.AEGIS_TEST_OIDC_DISCOVERY;

async function fillToken(page: import("@playwright/test").Page, value: string) {
  await page.goto("/login");
  if (sso) await page.getByText("Use an access token instead").click();
  await page.getByLabel("Access token").fill(value);
  await page.getByRole("button", { name: "Sign in with token" }).click();
}

async function login(page: import("@playwright/test").Page) {
  await fillToken(page, token);
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test("rejects a bad token and does not expose the token to scripts", async ({ page, context }) => {
  await fillToken(page, "not-a-token");
  await expect(page.getByText("Token rejected by the API.")).toBeVisible();
  // The browser can only reach allowlisted routes through the proxy.
  expect((await page.request.get("/api/aegis/v1/admin/anything")).status()).toBe(403);
  await login(page);
  const cookie = (await context.cookies()).find((c) => c.name === "aegis_token");
  expect(cookie?.httpOnly).toBe(true);
  expect(cookie?.sameSite).toBe("Strict");
  expect(await page.evaluate(() => document.cookie)).not.toContain("aegis_token");
});

test("run timeline, integrity status, and approval inbox reflect real state", async ({ page }) => {
  const project = await api.createProject(`pw-${Date.now()}`);
  const agent = await api.registerAgent(project.id, "pw-agent");
  await api.grantTool(agent.id, "calc.add", 0);
  await api.grantTool(agent.id, "data.export", 3);
  const { id } = await api.submitRun(agent.id, { task: "pw", mock_script: [
    { tool: "calc.add", args: { a: 1, b: 1 } },
    { tool: "email.send", args: { to: "x@evil.example", subject: "s", body: "b" } },
    { tool: "data.export", args: { dataset: "pw", destination: "s3.pw", classification: "INTERNAL" } },
    { final: "ok" },
  ] });
  expect((await api.waitForRun(id, 30_000)).state).toBe("WAITING_FOR_APPROVAL");

  await login(page);
  await page.goto(`/runs/${id}`);
  await expect(page.getByText("email.send — denied (no matching grant)")).toBeVisible();
  await expect(page.getByText("waiting on you").first()).toBeVisible();
  await page.getByRole("tab", { name: "evidence" }).click();
  await expect(page.getByText("Chain intact and signed")).toBeVisible();

  await page.goto("/approvals");
  const card = page.locator("li", { hasText: id });
  await expect(card).toContainText("data.export");
  await card.getByRole("button", { name: "Approve this exact action" }).click();
  await expect(page.locator("li", { hasText: id })).toHaveCount(0);
  expect((await api.waitForRun(id, 30_000)).state).toBe("SUCCEEDED");

  await page.goto("/security");
  await expect(page.getByRole("cell", { name: "no matching grant" }).first()).toBeVisible();

  // Policy simulator and grant management are live against the API.
  await page.goto("/agents");
  await page.getByRole("button", { name: /pw-agent/ }).first().click();
  await page.getByRole("button", { name: "Evaluate" }).click();
  await expect(page.getByText("Denied", { exact: true })).toBeVisible();
});

test("organization rules: change, see the effect, save, and view the report", async ({ page }) => {
  await login(page);
  await page.goto("/rules");
  await page.getByRole("button", { name: "Strict" }).click();
  await expect(page.getByText("You have unsaved changes")).toBeVisible();
  await page.getByRole("button", { name: "Discard" }).click();
  await expect(page.getByText("You have unsaved changes")).toHaveCount(0);

  await page.getByRole("radio", { name: /Irreversible only/ }).click();
  await page.getByRole("button", { name: "Save rules" }).click();
  await expect(page.getByText(/Rules saved/)).toBeVisible();
  await expect(page.getByText("Rules updated").first()).toBeVisible();

  await page.goto("/insights");
  await expect(page.getByText(/Healthy|Worth a look|Needs attention/).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Download report" })).toBeEnabled();
  // restore defaults for other tests
  await page.goto("/rules");
  await page.getByRole("button", { name: /^Balanced/ }).click();
  const save = page.getByRole("button", { name: "Save rules" });
  if (await save.isVisible()) await save.click();
});

test("memory page shows governed AegisMem activity, including blocked access", async ({ page }) => {
  const r = await fetch(`${process.env.AEGIS_API_URL ?? "http://127.0.0.1:8000"}/v1/tools`, { headers: { Authorization: `Bearer ${token}` } });
  const tools = ((await r.json()).items as { name: string }[]).map((t) => t.name);
  test.skip(!tools.includes("memory.recall"), "stack started without AEGIS_MEMORY_URL");
  const project = await api.createProject(`pw-mem-${Date.now()}`);
  const agent = await api.registerAgent(project.id, "pw-mem-agent");
  await api.grantTool(agent.id, "memory.remember", 2);
  const subject = `pw${Date.now()}`;
  const { id } = await api.submitRun(agent.id, { task: "pw", mock_script: [
    { tool: "memory.remember", args: { subject, text: "Playwright prefers dark mode" } },
    { tool: "memory.recall", args: { subject, query: "dark mode" } },  // no grant: denied
    { final: "ok" },
  ] });
  expect((await api.waitForRun(id, 30_000)).state).toBe("SUCCEEDED");

  await login(page);
  await page.getByRole("link", { name: "Memory" }).first().click();
  await expect(page.getByRole("heading", { name: "Memory" })).toBeVisible();
  const rows = page.locator("tr", { hasText: subject });
  await expect(rows.filter({ hasText: "Remembered" })).toHaveCount(1);
  await expect(rows.filter({ hasText: "Recalled" }).filter({ hasText: "no matching grant" })).toHaveCount(1);
});

test("memory page: clicking a subject shows what is stored and which run wrote it", async ({ page }) => {
  const r = await fetch(`${process.env.AEGIS_API_URL ?? "http://127.0.0.1:8000"}/v1/tools`, { headers: { Authorization: `Bearer ${token}` } });
  test.skip(!((await r.json()).items as { name: string }[]).some((t) => t.name === "memory.remember"), "stack started without AEGIS_MEMORY_URL");
  const project = await api.createProject(`pw-mem2-${Date.now()}`);
  const agent = await api.registerAgent(project.id, "pw-mem2-agent");
  await api.grantTool(agent.id, "memory.remember", 2);
  const subject = `pw${Date.now()}`;
  const { id } = await api.submitRun(agent.id, { task: "pw", mock_script: [
    { tool: "memory.remember", args: { subject, text: "Prefers invoices in EUR" } }, { final: "ok" },
  ] });
  expect((await api.waitForRun(id, 30_000)).state).toBe("SUCCEEDED");
  await login(page);
  await page.goto("/memory");
  await page.getByRole("button", { name: subject }).first().click();
  await expect(page.getByText(`Stored about ${subject}`)).toBeVisible();
  await expect(page.getByText("Prefers invoices in EUR")).toBeVisible();
  await page.getByRole("link", { name: /^from run_/ }).first().click();
  await expect(page).toHaveURL(new RegExp(`/runs/${id}`));
});

test.describe("single sign-on (OIDC authorization code + PKCE)", () => {
  test.skip(!sso, "AEGIS_TEST_OIDC_DISCOVERY not set");

  test("signs in through the identity provider, with the right access per user", async ({ page, context }) => {
    await page.goto("/login");
    await page.getByRole("link", { name: "Sign in", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Sign in to Aegis" })).toBeVisible();
    await page.getByRole("button", { name: /Dev admin/ }).click();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    const cookie = (await context.cookies()).find((c) => c.name === "aegis_token");
    expect(cookie?.httpOnly).toBe(true);
    expect((await context.cookies()).some((c) => c.name === "aegis_oidc" && c.value)).toBe(false);  // flow cookie cleared

    await page.getByRole("button", { name: "Sign out" }).click();
    await page.getByRole("link", { name: "Sign in", exact: true }).click();
    await page.getByRole("button", { name: /Dev auditor/ }).click();
    await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
    // The auditor token lacks payloads:read, so memory content is refused by the API.
    expect((await page.request.get("/api/aegis/v1/memory/acme")).status()).toBe(403);
  });

  test("rejects a callback that this browser did not start", async ({ page }) => {
    await page.goto("/auth/callback?code=stolen&state=" + "x".repeat(43));
    await expect(page.getByText("The sign-in took too long or was started in another browser")).toBeVisible();
  });

  test("rejects a forged state", async ({ page, context }) => {
    await page.goto("/login");
    // Start a real flow, then come back with a different state than the one this browser holds.
    const r = await page.request.get("/auth/login", { maxRedirects: 0 });
    const authorize = new URL(r.headers()["location"]);
    expect(authorize.searchParams.get("code_challenge_method")).toBe("S256");
    await page.goto(`/auth/callback?code=abc&state=${"y".repeat(43)}`);
    await expect(page.getByText("state mismatch")).toBeVisible();
    expect((await context.cookies()).some((c) => c.name === "aegis_token")).toBe(false);
  });
});

test("privacy: erase a finished run's content from its page; the erasure is logged", async ({ page }) => {
  const project = await api.createProject(`pw-erase-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`);
  const agent = await api.registerAgent(project.id, "pw-erase-agent");
  await api.grantTool(agent.id, "calc.add", 0);
  const { id } = await api.submitRun(agent.id, { task: "pw secret task", mock_script: [{ tool: "calc.add", args: { a: 1, b: 2 } }, { final: "secret answer" }] });
  expect((await api.waitForRun(id, 30_000)).state).toBe("SUCCEEDED");
  await login(page);
  await page.goto(`/runs/${id}`);
  await expect(page.getByText("secret answer").first()).toBeVisible();
  await page.getByRole("button", { name: "Place legal hold" }).click();
  await expect(page.getByRole("button", { name: "Erase content" })).toHaveCount(0);  // held runs cannot be erased
  await page.getByRole("button", { name: "Release legal hold" }).click();
  const reason = `customer deletion request ${id}`;  // unique: the erasure log persists across test runs
  page.once("dialog", (d) => d.accept(reason));
  await page.getByRole("button", { name: "Erase content" }).click();
  await expect(page.getByText("content erased", { exact: true })).toBeVisible();  // the badge, not the "Content erased" toast
  await expect(page.getByText("secret answer")).toHaveCount(0);
  await page.getByRole("tab", { name: "evidence" }).click();
  await expect(page.getByText("Chain intact and signed")).toBeVisible();  // evidence survives erasure
  await page.goto("/security");
  await expect(page.locator("tr", { hasText: reason })).toHaveCount(1);
});

test("visitors see the harness introduction first, with sign-in at the top right", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/welcome$/);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("Agents that act.");
  for (const p of ["Mem", "Trace", "Runtime", "Guard", "Eval", "Optimize", "Models", "Studio"]) {
    await expect(page.locator(`#pillar-${p.toLowerCase()}`)).toHaveCount(1);
  }
  const signIn = page.getByRole("banner").getByRole("link", { name: "Sign in" });
  const box = await signIn.boundingBox();
  expect(box && box.x > (page.viewportSize()?.width ?? 0) / 2).toBe(true);  // right-hand side of the top bar
  await signIn.click();
  await expect(page).toHaveURL(/\/login$/);
});

test("settings: create an API key, use it once from code, revoke it, and see both in the audit log", async ({ page }) => {
  const apiUrl = process.env.AEGIS_API_URL ?? "http://127.0.0.1:8000";
  const name = `pw-key-${Date.now()}`;
  await login(page);
  await page.goto("/settings/api-keys");
  await page.locator("#key-name").fill(name);
  await page.getByRole("button", { name: "Create key" }).click();
  const key = (await page.getByTestId("new-key").textContent())?.trim() ?? "";
  expect(key).toMatch(/^aet_[0-9a-f]{8}_/);
  expect((await fetch(`${apiUrl}/v1/runs?limit=1`, { headers: { Authorization: `Bearer ${key}` } })).status).toBe(200);
  await page.getByRole("button", { name: "Done" }).click();
  await expect(page.getByTestId("new-key")).toHaveCount(0);  // never shown again
  const row = page.locator("tr", { hasText: name });
  await row.getByRole("button", { name: "Revoke" }).click();
  await row.getByRole("button", { name: "Revoke now" }).click();
  await expect(row.getByText("revoked")).toBeVisible();
  expect((await fetch(`${apiUrl}/v1/runs?limit=1`, { headers: { Authorization: `Bearer ${key}` } })).status).toBe(401);
  await page.goto("/settings/audit");
  await expect(page.locator("tr", { hasText: "Created API key" }).first()).toBeVisible();
  await expect(page.locator("tr", { hasText: "Revoked API key" }).first()).toBeVisible();
});

test("usage: set a model price, run an agent, and see tokens and estimated cost", async ({ page }) => {
  await login(page);
  await page.goto("/settings/usage");
  await page.locator("#price-provider").fill("mock");
  await page.locator("#price-model").fill("mock-deterministic-1");
  await page.locator("#price-in").fill("3");
  await page.locator("#price-out").fill("15");
  await page.getByRole("button", { name: "Save price" }).click();
  await expect(page.locator("tr", { hasText: "mock/mock-deterministic-1" }).first()).toBeVisible();

  const project = await api.createProject(`pw-usage-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`);
  const agent = await api.registerAgent(project.id, "pw-usage-agent");
  await api.grantTool(agent.id, "calc.add", 0);
  const { id } = await api.submitRun(agent.id, { task: "usage", mock_script: [{ tool: "calc.add", args: { a: 1, b: 2 } }, { final: "3" }] });
  expect((await api.waitForRun(id, 30_000)).state).toBe("SUCCEEDED");
  await page.goto(`/runs/${id}`);
  await expect(page.getByText(/\d+ est\./)).toBeVisible();  // tokens, labelled as estimated
  await expect(page.getByText(/· \$0\.\d{4}/)).toBeVisible();  // cost from the price just set
  await page.goto("/settings/usage");
  await expect(page.locator("tr", { hasText: agent.id })).toBeVisible();
});

test("members: add a person, change their role, remove them", async ({ page }) => {
  const who = `usr_pw_${Date.now()}`;
  await login(page);
  await page.goto("/settings/members");
  await page.locator("#member-subject").fill(who);
  await page.locator("#member-role").selectOption("viewer");
  await page.getByRole("button", { name: "Add" }).click();
  const row = page.locator("tr", { hasText: who });
  await expect(row).toBeVisible();
  await row.getByLabel(`Role for ${who}`).selectOption("developer");
  await expect(page.getByText("Role changed")).toBeVisible();
  await row.getByRole("button", { name: "Remove" }).click();
  await expect(page.locator("tr", { hasText: who })).toHaveCount(0);
  await page.goto("/settings/audit");
  await expect(page.locator("tr", { hasText: who }).first()).toBeVisible();
});
