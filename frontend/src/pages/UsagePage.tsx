import { useEffect, useState } from "react";
import { api, type CreditEntry } from "../lib/api";
import { useAccess } from "../site/accessContext";
import { balanceLabel, creditsText, ledgerText, signed } from "../site/creditsModel";
import { amount, KINDS, usageRows } from "../site/usageModel";

// An invited person's credits, prices and allowance (ADR 0058, 0059).
export function UsagePage() {
  const status = useAccess();
  const [entries, setEntries] = useState<CreditEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const credits = status?.credits;
  useEffect(() => {
    let alive = true;
    api.myCredits().then(next => { if (alive) setEntries(next.entries); },
      () => { if (alive) setError("Your credit history could not be loaded. Try again in a moment."); });
    return () => { alive = false; };
  }, [credits]);
  const balance = balanceLabel(status);
  // A server runs one assistant provider: list only its price.
  const prices = Object.entries(status?.prices ?? {})
    .filter(([id, price]) => price.kind !== "assistant" || id === status?.assistant_item);
  return (
    <div className="h-full overflow-auto p-6">
      <div className="mx-auto max-w-3xl space-y-8">
        <header>
          <h1 className="text-xl font-semibold text-slate-900">Your usage</h1>
          <p className="mt-1 text-sm text-slate-500">
            Generating images, voices, assistant replies, release builds and trainings spends credits. Writing,
            editing and playtesting are free.
          </p>
        </header>
        {error && <p role="alert" className="rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

        {balance && <section aria-label="Credit balance" className="rounded-xl border border-amber-200 bg-amber-50 p-5">
          <p className="text-sm text-amber-900">Credits left</p>
          <p className="mt-1 text-3xl font-semibold text-slate-900">{balance}</p>
          {balance !== "Unlimited" && <p className="mt-2 text-sm text-amber-900">Need more? Ask the person who invited you.</p>}
        </section>}

        {status && <section aria-labelledby="allowance">
          <h2 id="allowance" className="font-semibold text-slate-900">Allowance</h2>
          <p className="mt-1 text-sm text-slate-500">
            {status.unlimited ? "Unlimited access has no caps." : "Caps limit how much you can make, whatever its price."}
          </p>
          <table className="mt-3 w-full overflow-hidden rounded-xl border border-slate-200 bg-white text-sm">
            <thead className="bg-slate-50 text-left text-slate-500">
              <tr><th className="px-4 py-2 font-medium">Kind</th><th className="px-4 py-2 font-medium">Last 24 hours</th><th className="px-4 py-2 font-medium">In total</th></tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {usageRows(status.unlimited ? null : status.limits, status.usage).map(row => (
                <tr key={row.kind}>
                  <td className="px-4 py-3 font-medium text-slate-800">{row.label}</td>
                  <td className="px-4 py-3 text-slate-600">{amount(row.day, row.daily)}</td>
                  <td className="px-4 py-3 text-slate-600">{amount(row.total, row.totalLimit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>}

        {!status?.unlimited && prices.length > 0 && <section aria-labelledby="prices">
          <h2 id="prices" className="font-semibold text-slate-900">Prices</h2>
          <div className="mt-3 grid gap-4 sm:grid-cols-2">
            {KINDS.map(([kind, label]) => {
              const items = prices.filter(([, price]) => price.kind === kind);
              if (!items.length) return null;
              return <div key={kind} className="rounded-xl border border-slate-200 bg-white p-4">
                <h3 className="text-sm font-medium text-slate-700">{label}</h3>
                <ul className="mt-2 space-y-1 text-sm">
                  {items.sort((a, b) => a[1].credits - b[1].credits).map(([id, price]) => (
                    <li key={id} className="flex justify-between gap-3">
                      <span className="text-slate-600">{price.label}</span>
                      <span className="whitespace-nowrap text-slate-900">{creditsText(price.credits)} / {price.unit}</span>
                    </li>
                  ))}
                </ul>
              </div>;
            })}
          </div>
        </section>}

        {entries && entries.length > 0 && <section aria-labelledby="history">
          <h2 id="history" className="font-semibold text-slate-900">Credit history</h2>
          <ul className="mt-3 divide-y divide-slate-100 rounded-xl border border-slate-200 bg-white text-sm">
            {entries.map(entry => (
              <li key={entry.id} className="flex items-center justify-between gap-3 px-4 py-2">
                <div className="min-w-0">
                  <p className="truncate text-slate-800">{ledgerText(entry, status?.prices)}</p>
                  <p className="text-xs text-slate-500">{new Date(entry.created_at).toLocaleString()}</p>
                </div>
                <div className="text-right">
                  <p className={entry.amount < 0 ? "text-slate-900" : "text-emerald-700"}>{signed(entry.amount)}</p>
                  {entry.balance !== null && <p className="text-xs text-slate-500">{entry.balance} left</p>}
                </div>
              </li>
            ))}
          </ul>
        </section>}
      </div>
    </div>
  );
}
