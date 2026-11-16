// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { NextResponse } from "next/server";
import { appUrl, discover, FLOW_COOKIE, OIDC, oidcEnabled, randomToken, s256 } from "@/lib/oidc";
import { SECURE_COOKIES } from "@/lib/session";

export async function GET(req: Request) {
  if (!oidcEnabled()) return NextResponse.redirect(appUrl("/login"), 303);
  let authorize: string;
  try {
    authorize = (await discover()).authorization_endpoint;
  } catch {
    return NextResponse.redirect(appUrl("/login?error=idp_unreachable"), 303);
  }
  const state = randomToken();
  const verifier = randomToken() + randomToken();
  const url = new URL(authorize);
  url.search = new URLSearchParams({
    response_type: "code", client_id: OIDC.clientId, redirect_uri: OIDC.redirectUri, scope: OIDC.scope,
    state, code_challenge: await s256(verifier), code_challenge_method: "S256",
    ...(OIDC.audience ? { audience: OIDC.audience } : {}),
  }).toString();
  const res = NextResponse.redirect(url, 303);
  // Lax (not Strict): the provider's redirect back to /auth/callback is a cross-site top-level navigation.
  res.cookies.set(FLOW_COOKIE, JSON.stringify({ state, verifier }), {
    httpOnly: true, sameSite: "lax", secure: SECURE_COOKIES, path: "/auth", maxAge: 600,
  });
  return res;
}
