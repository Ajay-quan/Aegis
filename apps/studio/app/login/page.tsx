// SPDX-License-Identifier: FSL-1.1-ALv2
// Copyright 2026 AegisTrace contributors
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { API_URL, TOKEN_COOKIE } from "@/lib/api";

async function login(form: FormData) {
  "use server";
  const token = String(form.get("token") ?? "").trim();
  const r = await fetch(`${API_URL}/v1/runs?limit=1`, { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" });
  if (!r.ok) redirect("/login?error=1");
  (await cookies()).set(TOKEN_COOKIE, token, {
    httpOnly: true, sameSite: "strict", secure: process.env.NODE_ENV === "production" && !API_URL.startsWith("http://127."),
    path: "/", maxAge: 8 * 3600,
  });
  redirect("/");
}

export default async function LoginPage({ searchParams }: { searchParams: Promise<Record<string, string>> }) {
  const sp = await searchParams;
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
          Paste an access token from your identity provider. It is stored in an httpOnly cookie on this server and never
          exposed to browser scripts.
        </p>
        {sp.error ? <p className="mt-4 rounded-md px-3 py-2 text-[13.5px]" style={{ background: "var(--red-bg)", color: "var(--red)" }}>Token rejected by the API.</p> : null}
        {sp.expired ? <p className="mt-4 rounded-md px-3 py-2 text-[13.5px]" style={{ background: "var(--neutral-bg)", color: "var(--text-2)" }}>Session expired. Sign in again.</p> : null}
        <form action={login} className="mt-5 flex flex-col gap-3">
          <label htmlFor="token" className="text-[13px] muted">Access token</label>
          <textarea id="token" name="token" required rows={5} autoComplete="off" spellCheck={false} className="input mono text-[12.5px]" />
          <button type="submit" className="btn btn-green h-9 justify-center">Sign in</button>
        </form>
        <p className="mt-6 text-[12.5px]" style={{ color: "var(--faint)" }}>Development tokens: <span className="mono">.dev/tokens.json</span></p>
      </div>
    </div>
  );
}
