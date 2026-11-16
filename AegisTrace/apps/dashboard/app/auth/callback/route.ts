// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { timingSafeEqual } from "node:crypto";
import { cookies } from "next/headers";
import { NextResponse } from "next/server";
import { appUrl, discover, FLOW_COOKIE, OIDC } from "@/lib/oidc";
import { startSession } from "@/lib/session";

const fail = (_req: Request, reason: string) => {
  const res = NextResponse.redirect(appUrl(`/login?error=${reason}`), 303);
  res.cookies.set(FLOW_COOKIE, "", { path: "/auth", maxAge: 0 });
  return res;
};

function sameString(a: string, b: string) {
  const x = Buffer.from(a), y = Buffer.from(b);
  return x.length === y.length && timingSafeEqual(x, y);
}

export async function GET(req: Request) {
  const q = new URL(req.url).searchParams;
  const raw = (await cookies()).get(FLOW_COOKIE)?.value;
  if (q.get("error")) return fail(req, "idp_denied");
  let flow: { state: string; verifier: string };
  try {
    flow = JSON.parse(raw ?? "");
  } catch {
    return fail(req, "flow_expired");
  }
  const code = q.get("code"), state = q.get("state");
  if (!code || !state || !sameString(state, flow.state)) return fail(req, "state_mismatch");

  let token: string | undefined;
  try {
    const body = new URLSearchParams({
      grant_type: "authorization_code", code, redirect_uri: OIDC.redirectUri, client_id: OIDC.clientId, code_verifier: flow.verifier,
      ...(OIDC.clientSecret ? { client_secret: OIDC.clientSecret } : {}),
    });
    const r = await fetch((await discover()).token_endpoint, {
      method: "POST", body, headers: { "content-type": "application/x-www-form-urlencoded", accept: "application/json" }, cache: "no-store",
    });
    if (r.ok) token = ((await r.json()) as { access_token?: string }).access_token;
  } catch {
    return fail(req, "idp_unreachable");
  }
  if (!token) return fail(req, "exchange_failed");
  if (!(await startSession(token))) return fail(req, "1");
  // The session cookie is SameSite=Strict, so a browser omits it on any request that is still part of
  // the redirect chain that began at the identity provider. Land on a page of our own first; its
  // refresh to the dashboard is a same-site navigation that carries the cookie.
  const res = new NextResponse(
    `<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0;url=${appUrl("/").pathname}">` +
      `<title>Signing in</title><p style="font:14px system-ui;color:#a4a8af;background:#060708">Signing in</p>`,
    { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } },
  );
  res.cookies.set(FLOW_COOKIE, "", { path: "/auth", maxAge: 0 });
  return res;
}
