// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
// OpenID Connect sign-in (authorization code + PKCE) against the organization's
// identity provider. The provider must issue access tokens for the AegisTrace
// API audience carrying the `aegis_tenant` claim and `scope`; the API validates
// them exactly as it validates any other token.
import "server-only";

export const OIDC = {
  discoveryUrl: process.env.AEGIS_OIDC_DISCOVERY_URL ?? "",
  clientId: process.env.AEGIS_OIDC_CLIENT_ID ?? "aegistrace-dashboard",
  clientSecret: process.env.AEGIS_OIDC_CLIENT_SECRET ?? "",  // optional: confidential clients
  scope: process.env.AEGIS_OIDC_SCOPE ?? "openid",
  audience: process.env.AEGIS_OIDC_AUDIENCE ?? "",  // optional: providers that select the API by audience (e.g. Auth0)
  providerName: process.env.AEGIS_OIDC_PROVIDER_NAME ?? "your identity provider",
  // The public URL of this dashboard; the callback must be registered with the provider.
  redirectUri: (process.env.AEGIS_DASHBOARD_URL ?? "http://localhost:3000").replace(/\/$/, "") + "/auth/callback",
};
export const FLOW_COOKIE = "aegis_oidc";
/** Absolute URL on this dashboard's public origin. Never derive it from the request: behind proxies (and
 *  with localhost vs 127.0.0.1) the request URL's host can differ from the one the session cookie belongs to. */
export const appUrl = (path: string) => new URL(path, OIDC.redirectUri);
export const oidcEnabled = () => OIDC.discoveryUrl !== "";
export const tokenPasteAllowed = () => process.env.AEGIS_DASHBOARD_TOKEN_LOGIN !== "0";

interface Discovery { authorization_endpoint: string; token_endpoint: string }
let cached: { at: number; doc: Discovery } | null = null;

export async function discover(): Promise<Discovery> {
  if (cached && Date.now() - cached.at < 5 * 60_000) return cached.doc;
  const r = await fetch(OIDC.discoveryUrl, { cache: "no-store" });
  if (!r.ok) throw new Error(`discovery ${r.status}`);
  const doc = (await r.json()) as Discovery;
  if (!doc.authorization_endpoint || !doc.token_endpoint) throw new Error("discovery document incomplete");
  cached = { at: Date.now(), doc };
  return doc;
}

const b64url = (b: ArrayBuffer | Uint8Array) => Buffer.from(b instanceof Uint8Array ? b : new Uint8Array(b)).toString("base64url");
export const randomToken = () => b64url(crypto.getRandomValues(new Uint8Array(32)));
export async function s256(verifier: string) {
  return b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
}
