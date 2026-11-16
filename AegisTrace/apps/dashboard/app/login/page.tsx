// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { redirect } from "next/navigation";
import { OIDC, oidcEnabled, tokenPasteAllowed } from "@/lib/oidc";
import { startSession } from "@/lib/session";

async function login(form: FormData) {
  "use server";
  if (!tokenPasteAllowed()) redirect("/login");
  const ok = await startSession(String(form.get("token") ?? "").trim());
  redirect(ok ? "/" : "/login?error=1");
}

const ERRORS: Record<string, string> = {
  "1": "Token rejected by the API.",
  idp_unreachable: "Could not reach the identity provider. Try again in a moment.",
  idp_denied: "Sign-in was cancelled or denied by the identity provider.",
  flow_expired: "The sign-in took too long or was started in another browser. Please start again.",
  state_mismatch: "Sign-in could not be verified (state mismatch). Please start again.",
  exchange_failed: "The identity provider did not issue an access token.",
};

export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string>> }) {
  const sp = await searchParams;
  const sso = oidcEnabled(), paste = tokenPasteAllowed();
  const tokenForm = (
    <form action={login} className="mt-4 flex flex-col gap-3">
      <label htmlFor="token" className="text-[13px] muted">Access token</label>
      <textarea id="token" name="token" required rows={5} autoComplete="off" spellCheck={false} className="input mono text-[12.5px]" />
      <button type="submit" className={`btn ${sso ? "" : "btn-green"} h-9 justify-center`}>Sign in with token</button>
      <p className="text-[12.5px]" style={{ color: "var(--faint)" }}>Development tokens: <span className="mono">.dev/tokens.json</span></p>
    </form>
  );
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-[380px] fade-in">
        <div className="mb-8 flex items-center gap-2">
          <span className="grid h-7 w-7 place-items-center rounded-md" style={{ background: "var(--green-bg)", border: "1px solid rgba(62,207,142,.35)" }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="var(--green)" strokeWidth="2.5"><path d="M12 3l8 4v5c0 5-3.5 8.5-8 9-4.5-.5-8-4-8-9V7l8-4z" /></svg>
          </span>
          <span className="text-[16px] font-semibold tracking-tight">AegisTrace</span>
        </div>
        <h1 className="text-[20px] font-semibold tracking-tight">Sign in</h1>
        <p className="mt-1.5 text-[14px] muted">
          {sso ? `Use your organization account through ${OIDC.providerName}.` : "Paste an access token from your identity provider."}{" "}
          Your session stays on this server in an httpOnly cookie and is never exposed to browser scripts.
        </p>
        {sp.error ? <p className="mt-4 rounded-md px-3 py-2 text-[13.5px]" style={{ background: "var(--red-bg)", color: "var(--red)" }}>{ERRORS[sp.error] ?? "Sign-in failed."}</p> : null}
        {sp.expired ? <p className="mt-4 rounded-md px-3 py-2 text-[13.5px]" style={{ background: "var(--neutral-bg)", color: "var(--text-2)" }}>Session expired. Sign in again.</p> : null}
        {sso ? <a href="/auth/login" className="btn btn-green mt-5 h-10 w-full justify-center text-[14.5px]">Sign in</a> : null}
        {paste ? (sso ? (
          <details className="mt-6">
            <summary className="cursor-pointer text-[13px] muted">Use an access token instead</summary>
            {tokenForm}
          </details>
        ) : tokenForm) : null}
        {!sso && !paste ? <p className="mt-4 text-[13.5px] muted">No sign-in method is configured. Set AEGIS_OIDC_DISCOVERY_URL.</p> : null}
      </div>
    </div>
  );
}
