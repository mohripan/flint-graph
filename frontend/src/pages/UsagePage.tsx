import { useEffect, useState } from "react";
import { api, type AccessStatus } from "../lib/api";
import { amount, usageRows } from "../site/usageModel";

// What an invited person has generated against their allowance (ADR 0058).
export function UsagePage() {
  const [status, setStatus] = useState<AccessStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    api.accessMe().then(next => { if (alive) setStatus(next); },
      () => { if (alive) setError("Usage could not be loaded. Try again in a moment."); });
    return () => { alive = false; };
  }, []);
  return (
    <div className="h-full overflow-auto p-6">
      <div className="mx-auto max-w-3xl">
        <h1 className="text-xl font-semibold text-slate-900">Your usage</h1>
        <p className="mt-1 text-sm text-slate-500">
          Your invitation includes an allowance for generating. Writing, editing and playtesting are never limited.
        </p>
        {error && <p role="alert" className="mt-4 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        {status && <table className="mt-6 w-full overflow-hidden rounded-xl border border-slate-200 bg-white text-sm">
          <thead className="bg-slate-50 text-left text-slate-500">
            <tr><th className="px-4 py-2 font-medium">Kind</th><th className="px-4 py-2 font-medium">Last 24 hours</th><th className="px-4 py-2 font-medium">In total</th></tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {usageRows(status.limits, status.usage).map(row => (
              <tr key={row.kind}>
                <td className="px-4 py-3 font-medium text-slate-800">{row.label}</td>
                <td className="px-4 py-3 text-slate-600">{amount(row.day, row.daily)}</td>
                <td className="px-4 py-3 text-slate-600">{amount(row.total, row.totalLimit)}</td>
              </tr>
            ))}
          </tbody>
        </table>}
      </div>
    </div>
  );
}
