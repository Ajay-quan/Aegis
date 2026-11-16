# Dashboard sign-in (single sign-on)

The dashboard signs people in with OpenID Connect (authorization code flow with PKCE) against your
organization's identity provider. The resulting access token is kept server-side in an httpOnly cookie;
browser scripts never see it. The API validates that token exactly as it validates any other.

## What the identity provider must issue

An **access token** (a JWT the API can verify) with:

| Claim | Value |
|---|---|
| `iss` | your provider's issuer; set the API's `AEGIS_OIDC_ISSUER` to it |
| `aud` | the API audience; set `AEGIS_OIDC_AUDIENCE` (default `aegistrace-api`) |
| `aegis_tenant` | the organization's AegisTrace tenant id, e.g. `tnt_acme` |
| `scope` | space-separated AegisTrace scopes (see below) |
| `sub`, `exp`, `iat`, `jti` | standard |

The API reads the provider's signing keys from `AEGIS_OIDC_JWKS` (a JWKS URL).

Most providers add custom claims through a rule, action or claim mapping: Okta (custom authorization
server claims), Microsoft Entra ID (app roles + claims mapping), Auth0 (Actions), Keycloak (protocol
mappers), Google (via an identity broker such as Keycloak).

Typical scope sets:
- **Operator:** `agents:read agents:write runs:read runs:write runs:reconcile policies:write receipts:export approvals:read approvals:decide replay:read replay:fork payloads:read audit:read`
- **Auditor:** `runs:read receipts:export replay:read audit:read` (no memory or payload content, cannot approve)

## Dashboard settings

| Variable | Meaning |
|---|---|
| `AEGIS_OIDC_DISCOVERY_URL` | the provider's `/.well-known/openid-configuration`; enables the Sign in button |
| `AEGIS_OIDC_CLIENT_ID` | the dashboard's client id (default `aegistrace-dashboard`) |
| `AEGIS_OIDC_CLIENT_SECRET` | only for confidential clients |
| `AEGIS_OIDC_SCOPE` | scopes to request from the provider (default `openid`) |
| `AEGIS_OIDC_AUDIENCE` | sent as `audience=` for providers that need it (Auth0) |
| `AEGIS_OIDC_PROVIDER_NAME` | shown on the sign-in page |
| `AEGIS_DASHBOARD_URL` | this dashboard's public URL. Register `<it>/auth/callback` as the redirect URI. All redirects use this origin. |
| `AEGIS_DASHBOARD_TOKEN_LOGIN=0` | turn off the "paste an access token" fallback (recommended in production) |

## Locally

`./aegis up` runs a **development** identity provider on `http://localhost:9000` (two users: a full-access
admin and a read-only auditor). It enforces exact redirect URIs, PKCE S256, single-use expiring codes and
client binding, so the dashboard is tested against a strict server. Never deploy it.
