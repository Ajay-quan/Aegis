// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { API_URL, TOKEN_COOKIE } from "@/lib/api";

export async function POST(req: NextRequest) {
  const jar = await cookies();
  const token = jar.get(TOKEN_COOKIE)?.value;
  if (token) {
    // Revoke server-side, not just forget locally.
    await fetch(`${API_URL}/v1/auth/logout`, { method: "POST", headers: { Authorization: `Bearer ${token}` } }).catch(() => {});
  }
  jar.delete(TOKEN_COOKIE);
  return NextResponse.redirect(new URL("/login", req.url), 303);
}
