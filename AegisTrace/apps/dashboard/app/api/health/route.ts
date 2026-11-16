// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { NextResponse } from "next/server";
import { API_URL } from "@/lib/api";

export async function GET() {
  const t0 = Date.now();
  try {
    const r = await fetch(`${API_URL}/readyz`, { cache: "no-store" });
    return NextResponse.json({ ...(await r.json()), latency_ms: Date.now() - t0 });
  } catch {
    return NextResponse.json({ status: "unreachable", checks: { api: "down" }, latency_ms: null }, { status: 503 });
  }
}
