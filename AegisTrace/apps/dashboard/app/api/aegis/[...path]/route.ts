// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// Same-origin proxy: the browser never sees the bearer token. Only an
// allowlisted set of API routes and methods is forwarded, and state-changing
// requests must come from this origin (defence in depth on top of SameSite=Strict).
import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";
import { API_URL, TOKEN_COOKIE } from "@/lib/api";

const ID = "[a-z]{3}_[a-f0-9]{24}";
const ALLOW: [string, RegExp][] = [
  ["GET", new RegExp(`^v1/(stats|stats/timeseries|runs|agents|tools|approvals|policy-decisions|signing-keys)$`)],
  ["GET", new RegExp(`^v1/runs/${ID}(/(events|replay|verification|receipt))?$`)],
  ["GET", new RegExp(`^v1/agents/${ID}/grants$`)],
  ["GET", /^v1\/(rules|rules\/history|rules\/file|insights)$/],
  ["PUT", /^v1\/rules$/],
  ["POST", /^v1\/rules\/file$/],
  ["POST", new RegExp(`^v1/(runs|projects|agents|policy/simulate)$`)],
  ["POST", new RegExp(`^v1/runs/${ID}/(cancel|reconcile)$`)],
  ["POST", new RegExp(`^v1/approvals/${ID}/decision$`)],
  ["PUT", new RegExp(`^v1/agents/${ID}/grants$`)],
  ["DELETE", new RegExp(`^v1/agents/${ID}/grants/[a-z0-9_.]{1,128}$`)],
];

async function handle(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const path = (await ctx.params).path.join("/");
  if (!ALLOW.some(([m, re]) => m === req.method && re.test(path))) {
    return NextResponse.json({ error: { code: "forbidden", message: "route not allowed" } }, { status: 403 });
  }
  if (req.method !== "GET") {
    const origin = req.headers.get("origin");
    if (!origin || new URL(origin).host !== req.headers.get("host")) {
      return NextResponse.json({ error: { code: "forbidden", message: "cross-origin request" } }, { status: 403 });
    }
  }
  const token = (await cookies()).get(TOKEN_COOKIE)?.value;
  if (!token) return NextResponse.json({ error: { code: "unauthenticated", message: "sign in" } }, { status: 401 });

  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const ct = req.headers.get("content-type");
  if (ct) headers["Content-Type"] = ct;
  const idem = req.headers.get("idempotency-key");
  if (idem) headers["Idempotency-Key"] = idem;
  const upstream = await fetch(`${API_URL}/${path}${req.nextUrl.search}`, {
    method: req.method,
    headers,
    body: req.method === "GET" || req.method === "DELETE" ? undefined : await req.text(),
    cache: "no-store",
  });
  const out = new NextResponse(upstream.status === 204 ? null : upstream.body, { status: upstream.status });
  for (const h of ["content-type", "content-disposition"]) {
    const v = upstream.headers.get(h);
    if (v) out.headers.set(h, v);
  }
  return out;
}

export { handle as GET, handle as POST, handle as PUT, handle as DELETE };
