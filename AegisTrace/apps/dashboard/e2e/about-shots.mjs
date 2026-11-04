// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { chromium } from "@playwright/test";
import fs from "node:fs";
const token = JSON.parse(fs.readFileSync(new URL("../../../.dev/tokens.json", import.meta.url))).user;
const out = (n) => new URL(`../../../.dev/shots/${n}.png`, import.meta.url).pathname;
const b = await chromium.launch();
const p = await b.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
await p.goto("http://127.0.0.1:3100/login");
await p.getByLabel("Access token").fill(token);
await p.getByRole("button", { name: "Sign in" }).click();
await p.getByRole("heading", { name: "Overview" }).waitFor();
await p.waitForTimeout(2500);
await p.screenshot({ path: out("a1-overview") });
await p.keyboard.press("Meta+i"); await p.waitForTimeout(400);
await p.screenshot({ path: out("a2-about") });
await p.keyboard.press("Escape");
await p.goto("http://127.0.0.1:3100/security"); await p.waitForTimeout(2000);
await p.screenshot({ path: out("a3-security") });
await b.close();
