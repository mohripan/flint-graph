import { useEffect, useState } from "react";
import { Spinner } from "../components/ui";
import { ApiError, api, type AccessStatus } from "../lib/api";
import { useAuth } from "../lib/auth";
import { CONTACT_EMAIL, CONTACT_HREF } from "./contact";
import { linkProps, navigate } from "./router";
import { SiteLayout } from "./SiteLayout";

// A proxy's "502 Bad Gateway" or a failed fetch means the server is down, not the key.
const message = (error: unknown) =>
  (error instanceof ApiError && error.status >= 500 && !error.problem) || error instanceof TypeError
    ? "FlintGraph's server can't be reached right now. Try again in a moment."
    : error instanceof Error && error.message ? error.message : "Something went wrong. Try again in a moment.";

// Joining an invite-only Studio (ADR 0058): sign in with any account, then redeem a key,
// or accept the email invitation that matches the verified address.
export function JoinPage() {
  const auth = useAuth();
  const signedIn = auth.mode === "dev" || auth.authenticated;
  const [key, setKey] = useState(() => new URLSearchParams(window.location.search).get("key") ?? "");
  const [status, setStatus] = useState<AccessStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (auth.loading || !signedIn) return;
    let alive = true;
    api.accessMe().then(next => { if (alive) setStatus(next); }, failure => { if (alive) setError(message(failure)); });
    return () => { alive = false; };
  }, [auth.loading, signedIn]);

  async function join(withKey: string | null) {
    setBusy(true); setError(null);
    try {
      const next = await api.joinStudio(withKey);
      setStatus(next);
      if (next.has_access) navigate("/studio");
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }

  const returnTo = "/join" + (key.trim() ? `?key=${encodeURIComponent(key.trim())}` : "");
  let body;
  if (auth.loading || (signedIn && !status && !error)) {
    body = <p role="status" className="flex items-center gap-2 text-slate-600"><Spinner className="h-4 w-4" /> Checking your invitation…</p>;
  } else if (!signedIn) {
    body = <>
      <p className="text-slate-600">Sign in first. Any account works: your invitation key or invited email connects it to FlintGraph.</p>
      <button type="button" onClick={() => auth.signIn(returnTo).catch(failure => setError(message(failure)))}
        className="mt-6 w-full rounded-lg bg-slate-900 px-4 py-3 font-semibold text-white transition hover:bg-slate-800">Sign in to continue</button>
    </>;
  } else if (status?.has_access) {
    body = <>
      <p className="text-slate-600">{status.mode === "open" ? "This Studio is open to everyone who signs in." : "You have access to the Studio."}</p>
      <a {...linkProps("/studio")} className="mt-6 block w-full rounded-lg bg-slate-900 px-4 py-3 text-center font-semibold text-white transition hover:bg-slate-800">Open the Studio</a>
    </>;
  } else if (status?.status === "suspended") {
    body = <p className="text-slate-600">Your access is paused. Contact the person who invited you to restore it.</p>;
  } else {
    body = <>
      {status?.email_invitation && <div className="mb-6 rounded-xl border border-amber-200 bg-amber-50 p-4">
        <p className="font-semibold text-amber-900">You have an invitation for {status.email}.</p>
        <button type="button" disabled={busy} onClick={() => void join(null)}
          className="mt-3 rounded-lg bg-amber-500 px-4 py-2 font-semibold text-slate-950 transition hover:bg-amber-400 disabled:opacity-50">
          Accept the invitation</button>
      </div>}
      <form onSubmit={event => { event.preventDefault(); if (key.trim()) void join(key.trim()); }}>
        <label htmlFor="invite-key" className="block text-sm font-semibold text-slate-800">Invitation key</label>
        <input id="invite-key" value={key} onChange={event => setKey(event.target.value)} autoComplete="off" spellCheck={false}
          placeholder="FG-XXXX-XXXX-XXXX-XXXX" maxLength={64}
          className="mt-2 w-full rounded-lg border border-slate-300 px-3 py-3 font-mono tracking-wider uppercase shadow-xs focus:border-amber-500 focus:ring-2 focus:ring-amber-200 focus:outline-hidden" />
        <button type="submit" disabled={busy || !key.trim()}
          className="mt-4 w-full rounded-lg bg-slate-900 px-4 py-3 font-semibold text-white transition hover:bg-slate-800 disabled:opacity-50">
          {busy ? "Joining…" : "Join FlintGraph"}</button>
      </form>
      <p className="mt-4 text-sm text-slate-500">No key yet? FlintGraph is invite-only for now. To ask for one, email <a href={CONTACT_HREF} className="underline">{CONTACT_EMAIL}</a>.</p>
    </>;
  }

  return (
    <SiteLayout current="join">
      <section className="site-hero flex justify-center px-4 py-16 sm:py-24">
        <div className="w-full max-w-md rounded-2xl bg-white p-8 shadow-2xl">
          <h1 className="site-serif text-3xl font-semibold text-slate-900">Join FlintGraph</h1>
          <div className="mt-4">{body}</div>
          {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
          {auth.mode === "oidc" && auth.authenticated && <p className="mt-6 border-t border-slate-100 pt-4 text-xs text-slate-500">
            Signed in{status?.email ? ` as ${status.email}` : ""}.{" "}
            <button type="button" className="underline" onClick={() => void auth.signOut()}>Use another account</button>
          </p>}
        </div>
      </section>
    </SiteLayout>
  );
}
