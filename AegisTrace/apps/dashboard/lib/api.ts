// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import "server-only";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { AegisClient, AuthenticationError } from "@aegistrace/sdk";

export const API_URL = process.env.AEGIS_API_URL ?? "http://127.0.0.1:8000";
export const TOKEN_COOKIE = "aegis_token";

/** Server-side only: the bearer token never reaches browser JavaScript. */
export async function client(): Promise<AegisClient> {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  if (!token) redirect("/login");
  return new AegisClient({ baseUrl: API_URL, token, maxRetries: 1 });
}

/** Raw GET for endpoints the SDK does not wrap yet. */
export async function apiGet<T>(path: string): Promise<T> {
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  if (!token) redirect("/login");
  const r = await fetch(API_URL + path, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  if (r.status === 401) redirect("/login?expired=1");
  if (!r.ok) throw new Error(`API ${r.status}`);
  return (await r.json()) as T;
}

export async function guarded<T>(fn: () => Promise<T>): Promise<T> {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof AuthenticationError) redirect("/login?expired=1");
    throw e;
  }
}
