// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import "server-only";
import { cookies } from "next/headers";
import { API_URL, TOKEN_COOKIE } from "@/lib/api";

/** Secure cookies everywhere except local plain-http setups (AEGIS_DASHBOARD_HTTP=1 in local compose). */
export const SECURE_COOKIES =
  process.env.NODE_ENV === "production" && !API_URL.startsWith("http://127.") && process.env.AEGIS_DASHBOARD_HTTP !== "1";

/** Accept a bearer token only if the API itself accepts it, then keep it server-side in an httpOnly cookie. */
export async function startSession(token: string): Promise<boolean> {
  const r = await fetch(`${API_URL}/v1/runs?limit=1`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  if (!r.ok) return false;
  (await cookies()).set(TOKEN_COOKIE, token, { httpOnly: true, sameSite: "strict", secure: SECURE_COOKIES, path: "/", maxAge: 8 * 3600 });
  return true;
}
