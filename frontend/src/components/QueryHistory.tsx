import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import type { QueryRunResponse } from "../lib/types";
import { Button, StatusPill } from "./ui";

const PAGE_SIZE = 25;

export function QueryHistory({ tenantId, revision, selectedId, disabled, onSelect }: {
  tenantId: string;
  revision: number;
  selectedId: string | null;
  disabled: boolean;
  onSelect: (run: QueryRunResponse) => void;
}) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [rows, setRows] = useState<QueryRunResponse[]>([]);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const detailsRef = useRef<HTMLDetailsElement | null>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setRows([]);
    setLoading(true);
    setError(null);
    setHasMore(false);
    void api.listQueryRuns(tenantId, { limit: PAGE_SIZE, query, signal: controller.signal })
      .then((next) => {
        if (controller.signal.aborted) return;
        setRows(next);
        setHasMore(next.length === PAGE_SIZE);
      })
      .catch(() => {
        if (!controller.signal.aborted) setError("Could not load question history. Try Refresh history.");
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => requestRef.current?.abort();
  }, [tenantId, query, revision]);

  async function loadMore() {
    if (loading || !rows.length) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const next = await api.listQueryRuns(tenantId, {
        limit: PAGE_SIZE, query, beforeId: rows[rows.length - 1].id, signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setRows((previous) => [...previous, ...next.filter((row) => !previous.some((item) => item.id === row.id))]);
      setHasMore(next.length === PAGE_SIZE);
    } catch {
      if (!controller.signal.aborted) setError("Could not load older questions. Try Load older questions again.");
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }

  return (
    <details ref={detailsRef} className="rounded-xl border border-slate-200 bg-white">
      <summary className="cursor-pointer rounded-xl px-4 py-3 text-sm font-semibold text-slate-700 focus-visible:outline-2 focus-visible:outline-brand-500">
        Question history
      </summary>
      <div className="border-t border-slate-100 px-4 pb-4 pt-3">
        <p className="mb-3 text-xs text-slate-500">Reopen saved answers and sources. Each question is independent; follow-up memory is not enabled yet.</p>
        <label className="block text-xs font-medium text-slate-600">
          Search questions
          <input value={search} onChange={(event) => setSearch(event.target.value)} maxLength={200}
            type="search" placeholder="Find an earlier question…"
            className="mt-1 w-full rounded-lg border border-slate-200 px-3 py-2 text-sm focus:outline-2 focus:outline-brand-500" />
        </label>
        {error && <p role="alert" className="mt-3 text-sm text-red-700">{error}</p>}
        <ul className="mt-3 divide-y divide-slate-100">
          {rows.map((run) => (
            <li key={run.id}>
              <button disabled={disabled} aria-label={run.query_text} aria-current={run.id === selectedId ? "true" : undefined}
                onClick={() => {
                  onSelect(run);
                  if (detailsRef.current) detailsRef.current.open = false;
                }}
                className="flex w-full flex-wrap items-center justify-between gap-2 rounded-lg px-2 py-3 text-left hover:bg-brand-50 focus-visible:outline-2 focus-visible:outline-brand-500 disabled:opacity-50">
                <span className="min-w-0 flex-1 break-words text-sm font-medium text-slate-800">{run.query_text}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <time dateTime={run.created_at} className="text-xs text-slate-500">{new Date(run.created_at).toLocaleDateString()}</time>
                  <StatusPill status={run.status} />
                </span>
              </button>
            </li>
          ))}
        </ul>
        {!loading && !error && rows.length === 0 && <p className="mt-3 text-sm text-slate-500">{query ? "No matching questions." : "No saved questions yet. Ask your first question below."}</p>}
        {loading && <p role="status" className="mt-3 text-sm text-slate-500">Loading history…</p>}
        {hasMore && <Button variant="secondary" className="mt-3" disabled={loading} onClick={() => void loadMore()}>Load older questions</Button>}
      </div>
    </details>
  );
}
