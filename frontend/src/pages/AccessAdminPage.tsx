import { useCallback, useEffect, useState } from "react";
import { Button } from "../components/ui";
import { api, type AccessGrant, type Invitation, type InvitationDraft } from "../lib/api";
import {
  amount, invitationMessage, invitationState, KINDS, limitsForm, parseLimits, usageRows, type Limits,
} from "../site/usageModel";

const message = (error: unknown) => error instanceof Error && error.message ? error.message : "That did not work. Try again.";
const STATE_LABEL = { active: "Active", used: "Used", expired: "Expired", revoked: "Revoked" } as const;
const input = "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-xs focus:border-brand-500 focus:ring-1 focus:ring-brand-500 focus:outline-hidden";

function copy(text: string) {
  void navigator.clipboard?.writeText(text);
}

// Operators create invitation keys and email invitations, and see who joined (ADR 0058).
export function AccessAdminPage() {
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [grants, setGrants] = useState<AccessGrant[]>([]);
  const [defaults, setDefaults] = useState<Limits>({});
  const [error, setError] = useState<string | null>(null);
  const [kind, setKind] = useState<"key" | "email">("key");
  const [label, setLabel] = useState("");
  const [email, setEmail] = useState("");
  const [uses, setUses] = useState("1");
  const [days, setDays] = useState("30");
  const [limits, setLimits] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<{ invitation: Invitation; key: string | null; link: string } | null>(null);

  const load = useCallback(async () => {
    try {
      const [list, people] = await Promise.all([api.listInvitations(), api.listAccessGrants()]);
      setInvitations(list.invitations); setGrants(people.grants); setDefaults(list.default_limits);
      setLimits(current => Object.keys(current).length ? current : limitsForm(list.default_limits));
    } catch (failure) {
      setError(message(failure));
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  async function create(event: React.FormEvent) {
    event.preventDefault();
    const parsed = parseLimits(limits);
    if (typeof parsed === "string") { setError(parsed); return; }
    const draft: InvitationDraft = { kind, label: label.trim(), limits: parsed };
    if (kind === "email") draft.email = email.trim();
    else draft.max_redemptions = Number(uses) || 1;
    if (days) draft.expires_at = new Date(Date.now() + Number(days) * 86_400_000).toISOString();
    setBusy(true); setError(null);
    try {
      const result = await api.createInvitation(draft);
      const link = new URL(result.link, window.location.origin).toString();
      setCreated({ ...result, link }); setLabel(""); setEmail("");
      await load();
    } catch (failure) {
      setError(message(failure));
    } finally {
      setBusy(false);
    }
  }

  async function act(run: () => Promise<unknown>) {
    setError(null);
    try { await run(); await load(); } catch (failure) { setError(message(failure)); }
  }

  return (
    <div className="h-full overflow-auto p-6">
      <div className="mx-auto max-w-5xl space-y-8">
        <header>
          <h1 className="text-xl font-semibold text-slate-900">Invitations</h1>
          <p className="mt-1 text-sm text-slate-500">
            Give a key to anyone, or invite one email address. Each invitation sets how much its person can generate.
          </p>
        </header>
        {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        {created && <section aria-label="New invitation" className="rounded-xl border border-emerald-200 bg-emerald-50 p-5">
          <h2 className="font-semibold text-emerald-900">Invitation “{created.invitation.label}” is ready</h2>
          {created.key && <>
            <p className="mt-1 text-sm text-emerald-800">Copy the key now: it is shown only once.</p>
            <p className="mt-3 rounded-lg bg-white px-3 py-2 font-mono text-lg tracking-wider text-slate-900">{created.key}</p>
          </>}
          <div className="mt-3 flex flex-wrap gap-2">
            {created.key && <Button variant="secondary" onClick={() => copy(created.key!)}>Copy key</Button>}
            <Button variant="secondary" onClick={() => copy(created.link)}>Copy link</Button>
            <Button variant="secondary" onClick={() => copy(invitationMessage(created.link, created.key))}>Copy message</Button>
            <Button variant="ghost" onClick={() => setCreated(null)}>Done</Button>
          </div>
        </section>}

        <section aria-labelledby="new-invitation" className="rounded-xl border border-slate-200 bg-white p-5">
          <h2 id="new-invitation" className="font-semibold text-slate-900">New invitation</h2>
          <form onSubmit={create} className="mt-4 space-y-4">
            <div className="flex gap-2" role="radiogroup" aria-label="Invitation kind">
              {(["key", "email"] as const).map(option => (
                <button key={option} type="button" role="radio" aria-checked={kind === option} onClick={() => setKind(option)}
                  className={`rounded-lg border px-3 py-1.5 text-sm ${kind === option ? "border-brand-500 bg-brand-50 text-brand-700" : "border-slate-300 text-slate-600"}`}>
                  {option === "key" ? "Invitation key" : "Email invitation"}
                </button>
              ))}
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <label className="text-sm font-medium text-slate-700">Label
                <input className={`${input} mt-1`} value={label} maxLength={120} required onChange={event => setLabel(event.target.value)}
                  placeholder={kind === "key" ? "e.g. ACME demo" : "e.g. Ana at ACME"} />
              </label>
              {kind === "email" ? <label className="text-sm font-medium text-slate-700">Email address
                <input className={`${input} mt-1`} type="email" value={email} required onChange={event => setEmail(event.target.value)} />
              </label> : <label className="text-sm font-medium text-slate-700">People who can use it
                <input className={`${input} mt-1`} type="number" min={1} max={1000} value={uses} onChange={event => setUses(event.target.value)} />
              </label>}
              <label className="text-sm font-medium text-slate-700">Expires
                <select className={`${input} mt-1`} value={days} onChange={event => setDays(event.target.value)}>
                  <option value="7">In 7 days</option><option value="30">In 30 days</option>
                  <option value="90">In 90 days</option><option value="">Never</option>
                </select>
              </label>
            </div>
            <fieldset>
              <legend className="text-sm font-medium text-slate-700">Allowance (blank means no limit, 0 means not included)</legend>
              <div className="mt-2 grid gap-2 sm:grid-cols-[10rem_1fr_1fr]">
                <span className="hidden text-xs text-slate-500 sm:block" /><span className="hidden text-xs text-slate-500 sm:block">Per 24 hours</span>
                <span className="hidden text-xs text-slate-500 sm:block">In total</span>
                {KINDS.map(([id, name]) => <div key={id} className="contents">
                  <span className="self-center text-sm text-slate-700">{name}</span>
                  {(["daily", "total"] as const).map(window => (
                    <input key={window} className={input} inputMode="numeric" aria-label={`${name} ${window === "daily" ? "per 24 hours" : "in total"}`}
                      value={limits[`${id}.${window}`] ?? ""} onChange={event => setLimits(current => ({ ...current, [`${id}.${window}`]: event.target.value }))} />
                  ))}
                </div>)}
              </div>
              <button type="button" className="mt-2 text-xs text-slate-500 underline" onClick={() => setLimits(limitsForm(defaults))}>Reset to the defaults</button>
            </fieldset>
            <Button type="submit" disabled={busy || !label.trim()}>{busy ? "Creating…" : kind === "key" ? "Create key" : "Create invitation"}</Button>
          </form>
        </section>

        <section aria-labelledby="invitation-list">
          <h2 id="invitation-list" className="font-semibold text-slate-900">All invitations</h2>
          {!invitations.length ? <p className="mt-2 text-sm text-slate-500">No invitations yet.</p> :
            <ul className="mt-3 divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
              {invitations.map(item => {
                const state = invitationState(item);
                return <li key={item.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm">
                  <div className="min-w-0">
                    <p className="font-medium text-slate-800">{item.label}</p>
                    <p className="text-slate-500">{item.kind === "key" ? `Key …${item.key_hint}` : item.email} · used {item.redemption_count} of {item.max_redemptions}
                      {item.expires_at ? ` · expires ${new Date(item.expires_at).toLocaleDateString()}` : ""}</p>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`rounded-full px-2 py-0.5 text-xs ${state === "active" ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>{STATE_LABEL[state]}</span>
                    {state === "active" && <Button variant="danger" onClick={() => void act(() => api.revokeInvitation(item.id))}>Revoke</Button>}
                  </div>
                </li>;
              })}
            </ul>}
        </section>

        <section aria-labelledby="people">
          <h2 id="people" className="font-semibold text-slate-900">People who joined</h2>
          {!grants.length ? <p className="mt-2 text-sm text-slate-500">Nobody has joined yet.</p> :
            <ul className="mt-3 divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white">
              {grants.map(grant => <li key={grant.id} className="px-4 py-3 text-sm">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="font-medium text-slate-800">{grant.display_name || grant.email || "Unnamed account"}</p>
                    <p className="text-slate-500">{grant.email}{grant.invitation_label ? ` · from “${grant.invitation_label}”` : ""}</p>
                  </div>
                  {grant.status === "active"
                    ? <Button variant="danger" onClick={() => void act(() => api.setAccessGrant(grant.id, "suspend"))}>Suspend</Button>
                    : <Button variant="secondary" onClick={() => void act(() => api.setAccessGrant(grant.id, "resume"))}>Resume</Button>}
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  {usageRows(grant.limits, grant.usage).map(row => `${row.label}: ${amount(row.day, row.daily)} today, ${amount(row.total, row.totalLimit)} total`).join(" · ")}
                </p>
              </li>)}
            </ul>}
        </section>
      </div>
    </div>
  );
}
