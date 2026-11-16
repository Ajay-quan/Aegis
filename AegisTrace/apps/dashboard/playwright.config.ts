// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "e2e",
  timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:3100" },
  webServer: {
    command: "npx next start -p 3100 -H 127.0.0.1",
    url: "http://127.0.0.1:3100/login",
    reuseExistingServer: false,
    env: {
      AEGIS_API_URL: process.env.AEGIS_API_URL ?? "http://127.0.0.1:8000",
      // Sign-in via the dev identity provider (./aegis up runs it on :9000).
      AEGIS_OIDC_DISCOVERY_URL: process.env.AEGIS_TEST_OIDC_DISCOVERY ?? "",
      AEGIS_OIDC_PROVIDER_NAME: "the dev identity provider",
      AEGIS_DASHBOARD_URL: "http://127.0.0.1:3100",
    },
  },
});
